import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'
import {
    InboxQuestionSource,
    captureInboxReportAction,
    discussQuestionProperties,
} from 'products/signals/frontend/inbox/inboxAnalytics'
import {
    REPORT_DISCUSSION_QUESTION_MAX_LENGTH,
    inboxTaskKickoffLogic,
} from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { newSessionSpace } from 'products/tasks/frontend/spaces/newSessionSceneLogic'

import { isSampleReportId } from './todaySampleReports'
import { reportPrompts } from './todaySignalReports'

/** Prompts that fill the composer, which starts a session about the report in the default space, like New session. */
export function TodayReportPrompts({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { discussReport } = useActions(inboxTaskKickoffLogic)
    const { sortedSpaces, lastSpaceId } = useValues(todaySpacesLogic)
    const space = newSessionSpace(sortedSpaces, null, lastSpaceId).space
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const [draft, setDraft] = useState('')
    const [pickedPrompt, setPickedPrompt] = useState<string | null>(null)
    const prompts = reportPrompts(report)
    const loading = isDiscussing || isCreatingPr
    const isOverLengthLimit = Array.from(draft.trim()).length > REPORT_DISCUSSION_QUESTION_MAX_LENGTH
    const disabledReason = isSampleReportId(report.id)
        ? 'Sample reports can’t start a session. Turn off sample reports to ask about a real one.'
        : isOverLengthLimit
          ? `Your message is too long. Shorten it to ${REPORT_DISCUSSION_QUESTION_MAX_LENGTH.toLocaleString()} characters or fewer.`
          : (aiConsentDisabledReason ?? undefined)

    const pickPrompt = (prompt: string): void => {
        setDraft(prompt)
        setPickedPrompt(prompt)
        textAreaRef.current?.focus()
    }

    const submit = (): void => {
        const question = draft.trim()
        if (!question || loading || disabledReason) {
            return
        }
        const source: InboxQuestionSource =
            pickedPrompt === null ? 'typed' : pickedPrompt === question ? 'suggested' : 'edited_suggestion'
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'today',
            extra: discussQuestionProperties({ source, suggestionCount: prompts.length }),
        })
        discussReport(report, reportUrl, question, undefined, undefined, { channelId: space?.id ?? null })
        setDraft('')
        setPickedPrompt(null)
    }

    return (
        <section className="TodayPrompts" aria-label="Ask about this report">
            <div className="Today__label">Ask about this report</div>
            <div className="flex flex-wrap gap-2">
                {prompts.map((prompt) => (
                    <LemonButton
                        key={prompt}
                        type="secondary"
                        size="small"
                        icon={<IconSparkles />}
                        onClick={() => pickPrompt(prompt)}
                        disabledReason={loading ? 'A session is starting.' : undefined}
                        data-attr="today-report-prompt"
                    >
                        {prompt}
                    </LemonButton>
                ))}
            </div>
            <Composer.Root
                value={draft}
                onChange={(value) => {
                    setDraft(value)
                    if (!value) {
                        setPickedPrompt(null)
                    }
                }}
                onSubmit={submit}
                loading={loading}
                disabled={loading}
                disabledReason={disabledReason}
                textAreaRef={textAreaRef}
            >
                <Composer.Frame>
                    <Composer.Field>
                        <Composer.Placeholder>Ask a question, or pick a prompt above</Composer.Placeholder>
                        <Composer.Textarea data-attr="today-report-prompt-input" />
                    </Composer.Field>
                </Composer.Frame>
                <Composer.Submit data-attr="today-report-prompt-submit" />
            </Composer.Root>
            <p className="TodayPrompts__hint">
                {space
                    ? `Starts a new session in the ${space.name} space with this report attached.`
                    : 'Starts a new session with this report attached.'}
            </p>
        </section>
    )
}
