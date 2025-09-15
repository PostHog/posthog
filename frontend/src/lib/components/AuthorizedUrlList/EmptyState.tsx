import { useActions } from 'kea'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconRefresh } from 'lib/lemon-ui/icons'

import { ExperimentIdType } from '~/types'

import { AuthorizedUrlListType, KeyedAppUrl, authorizedUrlListLogic } from './authorizedUrlListLogic'

type EmptyStateProps = {
    type: AuthorizedUrlListType
    experimentId?: ExperimentIdType | null
    actionId?: number | null
    displaySuggestions?: boolean
}

export function EmptyState({
    experimentId,
    actionId,
    type,
    displaySuggestions = true,
}: EmptyStateProps): JSX.Element | null {
    const logic = authorizedUrlListLogic({ experimentId: experimentId ?? null, actionId: actionId ?? null, type })
    const { urlsKeyed, suggestionsLoading, isAddUrlFormVisible } = useValues(logic)
    const { loadSuggestions } = useActions(logic)

    const domainOrUrl = type === AuthorizedUrlListType.RECORDING_DOMAINS ? 'domain' : 'URL'

    // Split suggestions and non-suggestions
    const [suggestionURLs, authorizedURLs] = urlsKeyed.reduce(
        ([suggestions, nonSuggestions], url) => {
            if (url.type === 'suggestion') {
                suggestions.push(url)
            } else {
                nonSuggestions.push(url)
            }
            return [suggestions, nonSuggestions]
        },
        [[], []] as KeyedAppUrl[][]
    )

    const children = useMemo(() => {
        // If there are authorized URLs, never display this empty state
        if (authorizedURLs.length > 0) {
            return null
        }

        // If the add URL form is visible, don't show the empty state either
        if (isAddUrlFormVisible) {
            return null
        }

        if (suggestionURLs.length > 0 && displaySuggestions) {
            return (
                <p className="mb-0">
                    There are no authorized {domainOrUrl}s. <br />
                    We've found some URLs you've used PostHog from in the last 3 days. Consider authorizing them. It'll
                    allow you to use these in{' '}
                    {type === AuthorizedUrlListType.RECORDING_DOMAINS ? (
                        <span>recordings.</span>
                    ) : (
                        <span>web analytics, web experiments and our toolbar.</span>
                    )}
                    <br />
                    <span>
                        {type === AuthorizedUrlListType.RECORDING_DOMAINS &&
                            'When no domains are specified, recordings will be authorized on all domains.'}
                    </span>
                </p>
            )
        }

        return (
            <div className="flex flex-row items-center justify-between w-full">
                <p>
                    <span className="font-bold">There are no authorized {domainOrUrl}s.</span>
                    <br />
                    Add one to get started. When you send us events we'll suggest the ones that you should authorize.
                    <br />
                    It'll allow you to use these in{' '}
                    {type === AuthorizedUrlListType.RECORDING_DOMAINS ? (
                        <span>recordings.</span>
                    ) : (
                        <span>web analytics, web experiments and our toolbar.</span>
                    )}
                    <br />
                    <span>
                        {type === AuthorizedUrlListType.RECORDING_DOMAINS &&
                            'When no domains are specified, recordings will be authorized on all domains.'}
                    </span>
                </p>

                {displaySuggestions && (
                    <div className="flex flex-col items-end gap-2">
                        <LemonButton
                            onClick={loadSuggestions}
                            disabled={suggestionsLoading}
                            type="secondary"
                            icon={<IconRefresh />}
                            data-attr="authorized-url-list-fetch-suggestions"
                        >
                            {suggestionsLoading ? 'Fetching...' : 'Fetch suggestions'}
                        </LemonButton>
                        <span className="text-small text-secondary">Sent an event? Refetch suggestions.</span>
                    </div>
                )}
            </div>
        )
    }, [
        authorizedURLs.length,
        isAddUrlFormVisible,
        suggestionURLs.length,
        suggestionsLoading,
        type,
        domainOrUrl,
        loadSuggestions,
        displaySuggestions,
    ])

    return children ? <div className="border rounded p-4 text-secondary">{children}</div> : null
}
