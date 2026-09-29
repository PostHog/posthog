import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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

import { reportPrompts } from './todaySignalReports'

/** Prompts that fill the composer, which starts a PostHog AI session about the report. */
export function TodayReportPrompts({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const [draft, setDraft] = useState('')
    const [pickedPrompt, setPickedPrompt] = useState<string | null>(null)
    const prompts = reportPrompts(report)
    const loading = isDiscussing || isCreatingPr
    const isOverLengthLimit = Array.from(draft.trim()).length > REPORT_DISCUSSION_QUESTION_MAX_LENGTH
    const disabledReason = isOverLengthLimit
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
        // Pointing the side panel at this report first makes the new session open there, even when the
        // panel still shows a discussion about another report.
        openReportDiscussion(report, reportUrl)
        discussReport(report, reportUrl, question)
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
                Starts a PostHog AI session with this report attached. It opens in the side panel.
            </p>
        </section>
    )
}
