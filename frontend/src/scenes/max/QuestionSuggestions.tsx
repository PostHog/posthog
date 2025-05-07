import { IconArrowUpRight, IconGear, IconShuffle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { productUrls } from '~/products'

import { maxLogic } from './maxLogic'

const QUESTION_SUGGESTIONS = [
    {
        label: 'Insights',
        suggestions: [
            'Create a funnel of the Pirate Metrics (AARRR)',
            'What are the most popular pages or screens?',
            'What is the distribution of paid vs organic traffic?',
            'What is the retention in the last two weeks?',
            'What are the top referring domains?',
            'Calculate a conversion rate for',
        ],
    },
    {
        label: 'Docs',
        suggestions: [
            'How can I create a feature flag?',
            'Where do I watch session replays?',
            'Help me set up an experiment',
            'What is the autocapture?',
            'How can I capture an exception?',
        ],
    },
    {
        label: 'Set up',
        suggestions: [
            'How can I set up session replay in',
            'How can I set up feature flags in',
            'How can I set up experiments in',
            'How can I set up data warehouse in',
            'How can I set up error tracking in',
            'How can I set up LLM Observability in',
            'How can I set up product analytics in',
        ],
    },
    {
        label: 'SQL',
        suggestions: ['Generate a SQL query to'],
        url: urls.sqlEditor(),
    },
    {
        label: 'Session Replay',
        suggestions: ['Find recordings'],
        url: productUrls.replay(),
    },
] as const

export function QuestionSuggestions(): JSX.Element {
    const { dataProcessingAccepted } = useValues(maxLogic)
    const { shuffleVisibleSuggestions } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    return (
        <div className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5 w-[min(48rem,100%)]">
            {QUESTION_SUGGESTIONS.map((suggestion, index) => (
                <LemonButton
                    key={index}
                    // onClick={() => askMax()}
                    size="xsmall"
                    type="secondary"
                    sideIcon={<IconArrowUpRight />}
                    center
                    className="shrink"
                    disabledReason={!dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined}
                >
                    {suggestion.label}
                </LemonButton>
            ))}
            <div className="flex gap-2">
                <LemonButton
                    onClick={shuffleVisibleSuggestions}
                    size="xsmall"
                    type="secondary"
                    icon={<IconShuffle />}
                    tooltip="Shuffle suggestions"
                />
                <LemonButton
                    onClick={() => openSettingsPanel({ sectionId: 'environment-max', settingId: 'core-memory' })}
                    size="xsmall"
                    type="secondary"
                    icon={<IconGear />}
                    tooltip="Edit Max's memory"
                />
            </div>
        </div>
    )
}
