import { IconChevronLeft } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { maxLogic, QUESTION_SUGGESTIONS_DATA, SuggestionGroup } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { checkSuggestionRequiresUserInput, stripSuggestionPlaceholders } from '../utils'

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
            askMax(suggestion.content)
        }
        setActiveGroup(null)
    }

    return {
        handleSuggestionGroupClick,
        handleSuggestionClick,
    }
}

interface FloatingSuggestionsDisplayProps {
    compact?: boolean
    showSuggestions: boolean
    dataProcessingAccepted: boolean
    type?: 'primary' | 'secondary' | 'tertiary'
    additionalSuggestions?: React.ReactNode[]
}

export function FloatingSuggestionsDisplay({
    compact = false,
    type = 'secondary',
    showSuggestions,
    dataProcessingAccepted,
    additionalSuggestions,
}: FloatingSuggestionsDisplayProps): JSX.Element | null {
    const { activeSuggestionGroup } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { handleSuggestionGroupClick, handleSuggestionClick } = useSuggestionHandling()

    if (!showSuggestions) {
        return null
    }

    return (
        <div className="mt-1 mx-1">
            {/* Main suggestion groups */}
            {(!activeSuggestionGroup || !compact) && (
                <>
                    <Tooltip title={!dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined}>
                        <ul
                            className={
                                compact
                                    ? 'flex flex-wrap gap-1'
                                    : 'flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5'
                            }
                        >
                            {QUESTION_SUGGESTIONS_DATA.map((group) => (
                                <li key={group.label}>
                                    <LemonButton
                                        key={group.label}
                                        onClick={() => handleSuggestionGroupClick(group)}
                                        size={compact ? 'xxsmall' : 'xsmall'}
                                        type={type}
                                        icon={group.icon}
                                        center={compact}
                                        fullWidth={!compact}
                                        tooltip={!dataProcessingAccepted ? undefined : group.tooltip}
                                        disabled={!dataProcessingAccepted}
                                    >
                                        {group.label}
                                    </LemonButton>
                                </li>
                            ))}
                            {additionalSuggestions?.map((suggestion, index) => (
                                <li key={index}>{suggestion}</li>
                            ))}
                        </ul>
                    </Tooltip>
                </>
            )}

            {/* Detailed suggestions when a group is active */}
            {activeSuggestionGroup && compact && (
                <>
                    <div className="flex items-center gap-1 mb-1">
                        <LemonButton
                            size="xxsmall"
                            type="tertiary"
                            icon={<IconChevronLeft />}
                            onClick={() => setActiveGroup(null)}
                            tooltip="Back to categories"
                        />
                        <div className="flex items-center gap-1">
                            {activeSuggestionGroup.icon}
                            <span className="text-xxs font-medium">{activeSuggestionGroup.label}</span>
                        </div>
                    </div>
                    <Tooltip title={!dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined}>
                        <div className="flex flex-col gap-1">
                            {activeSuggestionGroup.suggestions.map((suggestion, index) => (
                                <LemonButton
                                    key={index}
                                    onClick={() => handleSuggestionClick(suggestion)}
                                    size="xxsmall"
                                    type="tertiary"
                                    fullWidth
                                    disabled={!dataProcessingAccepted}
                                >
                                    {suggestion.content.replace(/\{[^}]*\}/g, '...')}
                                </LemonButton>
                            ))}
                        </div>
                    </Tooltip>
                </>
            )}
        </div>
    )
}
