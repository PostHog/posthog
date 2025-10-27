import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { QUESTION_SUGGESTIONS_DATA, SuggestionGroup, maxLogic } from '../maxLogic'
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
    dataProcessingAccepted: boolean
    type?: 'primary' | 'secondary' | 'tertiary'
    additionalSuggestions?: React.ReactNode[]
}

export function FloatingSuggestionsDisplay({
    type = 'secondary',
    dataProcessingAccepted,
    additionalSuggestions,
}: FloatingSuggestionsDisplayProps): JSX.Element | null {
    const { activeSuggestionGroup } = useValues(maxLogic)
    const { handleSuggestionGroupClick } = useSuggestionHandling()

    return (
        <div className="mt-1 mx-1">
            {/* Main suggestion groups */}
            {!activeSuggestionGroup && (
                <>
                    <Tooltip title={!dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined}>
                        <ul className="flex items-center justify-center flex-wrap gap-1.5">
                            {QUESTION_SUGGESTIONS_DATA.map((group) => (
                                <li key={group.label}>
                                    <LemonButton
                                        key={group.label}
                                        onClick={() => handleSuggestionGroupClick(group)}
                                        size="xsmall"
                                        type={type}
                                        icon={group.icon}
                                        center={false}
                                        fullWidth={true}
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
        </div>
    )
}
