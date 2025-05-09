import './QuestionSuggestions.scss'

import { IconBook, IconChevronLeft, IconGear, IconGraph, IconHogQL, IconPlug, IconRewindPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { urls } from 'scenes/urls'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { productUrls } from '~/products'

import { maxLogic } from './maxLogic'
import { questionSuggestionsLogic } from './questionSuggestionsLogic'

// Define and export SuggestionGroup type
export interface SuggestionGroup {
    readonly label: string
    readonly icon: JSX.Element
    readonly suggestions: readonly string[]
    readonly url?: string
}

// Export the data and type it with SuggestionGroup
export const QUESTION_SUGGESTIONS_DATA: readonly SuggestionGroup[] = [
    {
        label: 'Insights',
        icon: <IconGraph />,
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
        icon: <IconBook />,
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
        icon: <IconPlug />,
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
        icon: <IconHogQL />,
        suggestions: ['Generate a SQL query to'],
        url: urls.sqlEditor(),
    },
    {
        label: 'Session Replay',
        icon: <IconRewindPlay />,
        suggestions: ['Find recordings'],
        url: productUrls.replay(),
    },
] as const // as const is good for type inference, but SuggestionGroup[] ensures structure

export function QuestionSuggestions(): JSX.Element {
    const { dataProcessingAccepted } = useValues(maxLogic)
    const { askMax } = useActions(maxLogic) // Changed submit to askMax
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const logic = useMountedLogic(questionSuggestionsLogic)
    const { activeSuggestionGroup } = useValues(logic)
    const { setActiveSuggestionGroupLabel } = useActions(logic)

    // Key for re-rendering suggestion list to help reset animations
    const suggestionListKey = activeSuggestionGroup ? activeSuggestionGroup.label : 'categories'

    return (
        <div className="flex flex-col items-center justify-center w-[min(48rem,100%)] gap-y-2">
            {!activeSuggestionGroup ? (
                <>
                    <h3 className="w-full text-center text-xs font-medium mb-0 text-secondary">Ask Max about</h3>
                    <div className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5">
                        {QUESTION_SUGGESTIONS_DATA.map((group) => (
                            <LemonButton
                                key={group.label}
                                onClick={() => setActiveSuggestionGroupLabel(group.label)}
                                size="xsmall"
                                type="secondary"
                                icon={group.icon}
                                center
                                className="shrink"
                                disabledReason={
                                    !dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined
                                }
                            >
                                {group.label}
                            </LemonButton>
                        ))}
                    </div>
                </>
            ) : (
                <div className="w-full flex flex-col items-center gap-y-2" key={suggestionListKey}>
                    <div className="flex items-center justify-between w-full px-1 sm:px-2">
                        <LemonButton
                            icon={<IconChevronLeft />}
                            onClick={() => setActiveSuggestionGroupLabel(null)}
                            size="small"
                            type="tertiary"
                        >
                            Back
                        </LemonButton>
                        <h3 className="text-sm font-medium mb-0 text-primary text-center flex-1 truncate px-1">
                            {activeSuggestionGroup.label}
                        </h3>
                        <div className="text-right min-w-[60px]">
                            {' '}
                            {/* Replaced inline style with Tailwind class */}
                            {activeSuggestionGroup.url && (
                                <LemonButton size="small" type="secondary" to={activeSuggestionGroup.url} targetBlank>
                                    Go to {activeSuggestionGroup.label}
                                </LemonButton>
                            )}
                        </div>
                    </div>

                    <div className="flex flex-col gap-y-1.5 w-full items-stretch max-h-[200px] overflow-y-auto px-2">
                        {activeSuggestionGroup.suggestions.map((suggestionText: string, index: number) => (
                            <div
                                key={suggestionText}
                                className={`QuestionSuggestion fill-forwards delay-[${index * 40}ms]`}
                            >
                                <LemonButton
                                    fullWidth
                                    onClick={() => {
                                        askMax(suggestionText) // Changed submit to askMax
                                        setActiveSuggestionGroupLabel(null) // Close suggestions after asking
                                    }}
                                    size="small"
                                    type="tertiary"
                                    disabledReason={
                                        !dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined
                                    }
                                    title={suggestionText}
                                    className="justify-start text-left truncate"
                                >
                                    <span className="truncate">{suggestionText}</span>
                                </LemonButton>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            <div className="flex justify-center mt-1">
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
