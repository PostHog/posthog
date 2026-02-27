import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'

import { SuggestionGroup, SuggestionItem, maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

function useSuggestionHandling(): {
    handleSuggestionGroupClick: (group: SuggestionGroup) => void
    handleSuggestionClick: (suggestion: SuggestionItem) => void
} {
    const { setQuestion, focusInput, setActiveGroup } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)

    const handleSuggestionGroupClick = (group: SuggestionGroup): void => {
        // If it's a product-based skill, open the URL first (but not when on /ai route)
        const cleanPath = removeProjectIdIfPresent(router.values.currentLocation.pathname)
        const isOnAiRoute = cleanPath.startsWith('/ai')
        if (group.url && !isOnAiRoute && !cleanPath.includes(group.url)) {
            router.actions.push(group.url)
        }

        // If there's only one suggestion, we can just ask Max directly
        if (group.suggestions.length <= 1) {
            if (group.suggestions[0].requiresUserInput) {
                setQuestion(group.suggestions[0].content)
                focusInput()
            } else {
                setQuestion(group.suggestions[0].content)
                askMax(group.suggestions[0].content)
            }
        } else {
            setActiveGroup(group)
        }
    }

    const handleSuggestionClick = (suggestion: SuggestionItem): void => {
        if (suggestion.requiresUserInput) {
            setQuestion(suggestion.content)
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

interface FloatingSuggestionsDisplayProps {
    dataProcessingAccepted: boolean
    dataProcessingApprovalDisabledReason?: string | null
    suggestionsData: readonly SuggestionGroup[]
    type?: 'primary' | 'secondary' | 'tertiary'
    additionalSuggestions?: React.ReactNode[]
}

export function FloatingSuggestionsDisplay({
    type = 'secondary',
    dataProcessingAccepted,
    dataProcessingApprovalDisabledReason,
    suggestionsData,
    additionalSuggestions,
}: FloatingSuggestionsDisplayProps): JSX.Element | null {
    const { activeSuggestionGroup } = useValues(maxLogic)
    const { handleSuggestionGroupClick } = useSuggestionHandling()

    return (
        <div className={cn('mt-1 mx-1', activeSuggestionGroup && 'fade-out pointer-events-none')}>
            {/* Main suggestion groups */}
            <>
                <Tooltip
                    title={
                        !dataProcessingAccepted
                            ? dataProcessingApprovalDisabledReason || 'Please accept AI data processing'
                            : undefined
                    }
                >
                    <ul className="flex items-center justify-center flex-wrap gap-1.5">
                        {suggestionsData.map((group) => (
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
        </div>
    )
}
