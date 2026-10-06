import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Composer } from 'products/posthog_ai/frontend/api/composer'
import {
    InboxQuestionSource,
    captureInboxReportAction,
    discussQuestionProperties,
} from 'products/signals/frontend/inbox/inboxAnalytics'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'
import { reportPrompts } from './todaySignalReports'

/** Prompts and a composer that open PostHog AI with the report as context. A prompt sends at once. */
export function TodayReportPrompts({ report }: { report: SignalReport }): JSX.Element {
    const { askingAi } = useValues(todayLogic)
    const { askAi } = useActions(todayLogic)
    const [draft, setDraft] = useState('')
    const prompts = reportPrompts(report)
    const disabledReason = isSampleReportId(report.id)
        ? 'Sample reports can’t start a chat. Turn off sample reports to ask about a real one.'
        : undefined

    const ask = (question: string, source: InboxQuestionSource): void => {
        if (!question || disabledReason || askingAi) {
            return
        }
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'today',
            extra: discussQuestionProperties({ source, suggestionCount: prompts.length }),
        })
        askAi(question, 'report_page', report)
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
                        onClick={() => ask(prompt, 'suggested')}
                        disabledReason={disabledReason ?? (askingAi ? 'Opening PostHog AI…' : undefined)}
                        data-attr="today-report-prompt"
                    >
                        {prompt}
                    </LemonButton>
                ))}
            </div>
            <Composer.Root
                value={draft}
                onChange={setDraft}
                onSubmit={() => {
                    ask(draft.trim(), 'typed')
                    setDraft('')
                }}
                disabledReason={disabledReason}
                loading={askingAi}
                disabled={askingAi}
            >
                <Composer.Frame>
                    <Composer.Field>
                        <Composer.Placeholder>Or ask your own question</Composer.Placeholder>
                        <Composer.Textarea data-attr="today-report-prompt-input" />
                    </Composer.Field>
                </Composer.Frame>
                <Composer.Submit data-attr="today-report-prompt-submit" />
            </Composer.Root>
            <p className="TodayPrompts__hint">Opens PostHog AI with this report as context.</p>
        </section>
    )
}
