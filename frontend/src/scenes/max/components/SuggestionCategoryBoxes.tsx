import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { QUESTION_SUGGESTIONS_DATA, SuggestionGroup, maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { checkSuggestionRequiresUserInput, formatSuggestion, stripSuggestionPlaceholders } from '../utils'

function useSuggestionHandling(): {
    handleSuggestionGroupClick: (group: SuggestionGroup) => void
    handleSuggestionClick: (suggestion: { content: string }) => void
} {
    const { setQuestion, focusInput, setActiveGroup } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)

    const handleSuggestionGroupClick = (group: SuggestionGroup): void => {
        // If it's a product-based skill, open the URL first
        if (group.url && !router.values.currentLocation.pathname.includes(group.url)) {
            router.actions.push(group.url)
        }

        // If there's only one suggestion, we can just ask Max directly
        if (group.suggestions.length <= 1) {
            if (checkSuggestionRequiresUserInput(group.suggestions[0].content)) {
                setQuestion(stripSuggestionPlaceholders(group.suggestions[0].content))
                focusInput()
            } else {
                setQuestion(group.suggestions[0].content)
                askMax(group.suggestions[0].content)
            }
        } else {
            setActiveGroup(group)
        }
    }

    const handleSuggestionClick = (suggestion: { content: string }): void => {
        if (checkSuggestionRequiresUserInput(suggestion.content)) {
            setQuestion(stripSuggestionPlaceholders(suggestion.content))
            focusInput()
        } else {
            setQuestion(suggestion.content)
            askMax(suggestion.content)
        }
        setActiveGroup(null)
    }

    return {
        handleSuggestionGroupClick,
        handleSuggestionClick,
    }
}

export function SuggestionCategoryBoxes(): JSX.Element {
    const { activeSuggestionGroup } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { handleSuggestionGroupClick, handleSuggestionClick } = useSuggestionHandling()

    const handleBackClick = (): void => {
        setActiveGroup(null)
    }

    // Show expanded suggestions list when a category is selected
    if (activeSuggestionGroup) {
        return (
            <div className="w-full max-w-3xl mx-auto px-4">
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 mb-1">
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconArrowLeft />}
                            onClick={handleBackClick}
                            aria-label="Back to categories"
                            tabIndex={0}
                        />
                        <div className="flex items-center gap-2">
                            <span className="[&_svg]:size-5">{activeSuggestionGroup.icon}</span>
                            <span className="font-semibold text-base">{activeSuggestionGroup.label}</span>
                        </div>
                    </div>
                    <ul className="flex flex-col gap-1">
                        {activeSuggestionGroup.suggestions.map((suggestion, index) => (
                            <li key={index}>
                                <LemonButton
                                    onClick={() => handleSuggestionClick(suggestion)}
                                    type="secondary"
                                    fullWidth
                                    className="justify-start text-left"
                                    disabled={!dataProcessingAccepted}
                                    tabIndex={0}
                                    aria-label={`Ask: ${formatSuggestion(suggestion.content)}`}
                                >
                                    {formatSuggestion(suggestion.content)}
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                </div>
            </div>
        )
    }

    // Show category boxes grid
    return (
        <div className="w-full max-w-3xl mx-auto px-4">
            <Tooltip title={!dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined}>
                <ul
                    className={cn(
                        'grid grid-cols-2 md:grid-cols-3 gap-3',
                        !dataProcessingAccepted && 'opacity-50 pointer-events-none'
                    )}
                >
                    {QUESTION_SUGGESTIONS_DATA.map((group) => (
                        <li key={group.label}>
                            <button
                                onClick={() => handleSuggestionGroupClick(group)}
                                disabled={!dataProcessingAccepted}
                                className={cn(
                                    'w-full p-2 rounded-lg border border-secondary',
                                    'bg-surface-primary hover:bg-surface-secondary',
                                    'transition-colors cursor-pointer text-left',
                                    'focus:outline-none focus:ring-2 focus:ring-accent',
                                    'disabled:cursor-not-allowed disabled:opacity-50'
                                )}
                                tabIndex={0}
                                aria-label={`${group.label}: ${group.suggestions.length} suggestions`}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault()
                                        handleSuggestionGroupClick(group)
                                    }
                                }}
                            >
                                <div className="flex flex-col gap-4">
                                    <div className="flex items-center justify-center size-4 rounded-lg bg-accent-light [&_svg]:size-5">
                                        {group.icon}
                                    </div>
                                    <div className="flex flex-col gap-0.5">
                                        <span className="font-semibold text-sm">{group.label}</span>
                                        <span className="text-xs text-secondary">
                                            {group.suggestions.length}{' '}
                                            {group.suggestions.length === 1 ? 'suggestion' : 'suggestions'}
                                        </span>
                                    </div>
                                </div>
                            </button>
                        </li>
                    ))}
                </ul>
            </Tooltip>
        </div>
    )
}
