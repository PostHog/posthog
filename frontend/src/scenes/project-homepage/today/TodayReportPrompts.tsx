import { useActions, useValues } from 'kea'
import { Fragment, useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Button, Heading, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

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

import { isSampleReportId } from './todaySampleReports'
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
        // Pointing the side panel at this report first makes the new session open there, even when the
        // panel still shows a discussion about another report.
        openReportDiscussion(report, reportUrl)
        discussReport(report, reportUrl, question)
        setDraft('')
        setPickedPrompt(null)
    }

    return (
        <section className="flex flex-col gap-3" aria-label="Ask about this report">
            <Heading size="sm" render={<h2 />}>
                Ask about this report
            </Heading>
            <div className="flex flex-wrap gap-2">
                {prompts.map((prompt) => {
                    const button = (
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={loading}
                            onClick={() => pickPrompt(prompt)}
                            data-attr="today-report-prompt"
                        >
                            <IconSparkles />
                            {prompt}
                        </Button>
                    )
                    return loading ? (
                        <Tooltip key={prompt}>
                            <TooltipTrigger render={button} />
                            <TooltipContent>A session is starting.</TooltipContent>
                        </Tooltip>
                    ) : (
                        <Fragment key={prompt}>{button}</Fragment>
                    )
                })}
            </div>
            {/* The composer is shared with PostHog AI, so it stays on LemonUI. */}
            <div data-not-quill>
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
            </div>
            <Text size="xs" variant="muted">
                Starts a PostHog AI session with this report attached. It opens in the side panel.
            </Text>
        </section>
    )
}
