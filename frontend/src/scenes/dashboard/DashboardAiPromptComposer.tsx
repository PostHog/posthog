import { useActions, useValues } from 'kea'
import type { FormEvent } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { dashboardAiPromptComposerLogic } from './dashboardAiPromptComposerLogic'

type SamplePromptPreview = 'activity' | 'adoption' | 'retention' | 'paths'

const SAMPLE_PROMPTS: { question: string; prompt: string; preview: SamplePromptPreview }[] = [
    {
        question: 'What does user activity look like this week?',
        prompt: 'Build a product activity dashboard for the past 7 days. Show daily active users, new and returning users, top events, and day-over-day change. Add the insights to this dashboard.',
        preview: 'activity',
    },
    {
        question: 'How is my feature being adopted?',
        prompt: 'Build a feature adoption dashboard. Show unique users for each key feature, adoption over time, new adopters, and retention of adopters. Add the insights to this dashboard.',
        preview: 'adoption',
    },
    {
        question: 'What brings users back after they sign up?',
        prompt: 'Build a retention dashboard. Show weekly retention cohorts, returning users after signup, and retention by signup source. Add the insights to this dashboard.',
        preview: 'retention',
    },
    {
        question: 'Which paths lead users to activation?',
        prompt: 'Build a user paths dashboard. Show the most common event sequences before activation, where users drop off, and the paths used by activated users. Add the insights to this dashboard.',
        preview: 'paths',
    },
]

function SamplePromptPreview({ preview }: { preview: SamplePromptPreview }): JSX.Element {
    if (preview === 'activity') {
        return (
            <svg
                aria-hidden
                className="h-8 w-16 shrink-0 text-[var(--color-product-product-analytics-light)]"
                viewBox="0 0 80 40"
            >
                <rect x="2" y="4" width="9" height="32" fill="currentColor" />
                <rect x="17" y="14" width="9" height="22" fill="currentColor" opacity="0.25" />
                <rect x="32" y="8" width="9" height="28" fill="currentColor" opacity="0.45" />
                <rect x="47" y="18" width="9" height="18" fill="currentColor" />
                <rect x="62" y="11" width="9" height="25" fill="currentColor" opacity="0.65" />
            </svg>
        )
    }

    if (preview === 'adoption') {
        return (
            <svg
                aria-hidden
                className="h-8 w-16 shrink-0 text-[var(--color-product-product-analytics-light)]"
                viewBox="0 0 80 40"
            >
                <rect x="2" y="4" width="28" height="32" rx="2" fill="currentColor" opacity="0.9" />
                <rect x="36" y="4" width="19" height="7" rx="1" fill="currentColor" opacity="0.25" />
                <rect x="36" y="17" width="34" height="7" rx="1" fill="currentColor" />
                <rect x="36" y="30" width="12" height="6" rx="1" fill="currentColor" opacity="0.4" />
            </svg>
        )
    }

    if (preview === 'retention') {
        return (
            <svg
                aria-hidden
                className="h-8 w-16 shrink-0 text-[var(--color-product-product-analytics-light)]"
                viewBox="0 0 80 40"
            >
                <path
                    d="M4 31C16 27 19 11 31 15s12 16 23 10 13-16 22-20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="4"
                />
                <circle cx="4" cy="31" r="3" fill="currentColor" />
                <circle cx="31" cy="15" r="3" fill="currentColor" opacity="0.7" />
                <circle cx="54" cy="25" r="3" fill="currentColor" opacity="0.5" />
                <circle cx="76" cy="5" r="3" fill="currentColor" opacity="0.3" />
            </svg>
        )
    }

    return (
        <svg
            aria-hidden
            className="h-8 w-16 shrink-0 text-[var(--color-product-product-analytics-light)]"
            viewBox="0 0 80 40"
        >
            <path d="M10 10h20l12 10h20" fill="none" stroke="currentColor" strokeWidth="4" />
            <circle cx="10" cy="10" r="5" fill="currentColor" />
            <circle cx="42" cy="20" r="5" fill="currentColor" opacity="0.6" />
            <circle cx="62" cy="20" r="5" fill="currentColor" opacity="0.35" />
        </svg>
    )
}

export type DashboardAiPromptComposerProps = {
    dashboardId?: number
    disabledReason?: string | null
    onOpenAiWithPrompt: (prompt: string) => void
}

export function DashboardAiPromptComposer({
    dashboardId,
    disabledReason,
    onOpenAiWithPrompt,
}: DashboardAiPromptComposerProps): JSX.Element {
    const { prompt, promptSource } = useValues(dashboardAiPromptComposerLogic)
    const { setPrompt } = useActions(dashboardAiPromptComposerLogic)
    const { reportDashboardEmptyAiPromptClicked, reportDashboardEmptyAiPromptSubmitted } = useActions(eventUsageLogic)

    const submitPrompt = (event: FormEvent<HTMLFormElement>): void => {
        event.preventDefault()

        const question = prompt.trim()
        if (!question) {
            return
        }

        reportDashboardEmptyAiPromptClicked(
            promptSource === 'starter_question' ? 'Starter question' : 'Custom question',
            dashboardId,
            promptSource
        )
        reportDashboardEmptyAiPromptSubmitted(dashboardId, promptSource)
        onOpenAiWithPrompt(question)
        setPrompt('')
    }

    return (
        <form className="w-full" onSubmit={submitPrompt}>
            <label htmlFor="dashboard-ai-prompt-composer-input" className="block text-sm font-semibold mb-1">
                What do you want to learn?
            </label>
            <LemonTextArea
                id="dashboard-ai-prompt-composer-input"
                value={prompt}
                onChange={setPrompt}
                placeholder="For example, which pages convert best?"
                minRows={3}
                maxRows={5}
                disabled={!!disabledReason}
                data-attr="dashboard-ai-prompt-composer-input"
            />
            <div className="flex items-center justify-between gap-4 mt-2">
                <Link
                    to="https://posthog.com/docs/web-analytics/web-vs-product-analytics"
                    target="_blank"
                    targetBlankIcon
                    className="text-sm"
                >
                    Learn about product analytics
                </Link>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={disabledReason || (prompt.trim() ? undefined : 'Enter a question')}
                    data-attr="dashboard-ai-prompt-composer-submit"
                >
                    Build it for me
                </LemonButton>
            </div>
            <div className="mt-5">
                <p className="text-sm font-semibold m-0 mb-2">Start with a question</p>
                <div className="flex flex-col gap-2">
                    {SAMPLE_PROMPTS.map(({ question, prompt, preview }) => (
                        <LemonButton
                            key={question}
                            type="secondary"
                            htmlType="button"
                            fullWidth
                            className="!h-14 !rounded-lg !border-border !bg-bg-surface-primary !px-0 !py-0 !text-left !text-base !font-normal shadow-none hover:!bg-fill-secondary"
                            onClick={() => {
                                reportDashboardEmptyAiPromptClicked(question, dashboardId, 'starter_question')
                                setPrompt(prompt, 'starter_question')
                            }}
                            disabledReason={disabledReason || undefined}
                        >
                            <span className="flex w-full items-center justify-between gap-4">
                                <span>{question}</span>
                                <SamplePromptPreview preview={preview} />
                            </span>
                        </LemonButton>
                    ))}
                </div>
            </div>
        </form>
    )
}
