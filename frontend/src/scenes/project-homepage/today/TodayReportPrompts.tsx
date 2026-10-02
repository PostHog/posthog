import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'
import {
    InboxQuestionSource,
    captureInboxReportAction,
    discussQuestionProperties,
} from 'products/signals/frontend/inbox/inboxAnalytics'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'
import { reportPrompts } from './todaySignalReports'

/** Prompts that fill the composer, which opens PostHog AI with the report as context. */
export function TodayReportPrompts({ report }: { report: SignalReport }): JSX.Element {
    const { askAi } = useActions(todayLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const [draft, setDraft] = useState('')
    const [pickedPrompt, setPickedPrompt] = useState<string | null>(null)
    const prompts = reportPrompts(report)
    const disabledReason = isSampleReportId(report.id)
        ? 'Sample reports can’t start a chat. Turn off sample reports to ask about a real one.'
        : undefined

    const pickPrompt = (prompt: string): void => {
        setDraft(prompt)
        setPickedPrompt(prompt)
        textAreaRef.current?.focus()
    }

    const submit = (): void => {
        const question = draft.trim()
        if (!question || disabledReason) {
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
        askAi(question, 'report_page', report)
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
            <p className="TodayPrompts__hint">Opens PostHog AI with this report as context.</p>
        </section>
    )
}
