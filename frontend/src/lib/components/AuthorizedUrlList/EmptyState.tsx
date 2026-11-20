import { useActions } from 'kea'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { ExperimentIdType } from '~/types'

import { AuthorizedUrlListType, KeyedAppUrl, authorizedUrlListLogic } from './authorizedUrlListLogic'
import { QuillAuthorizedUrlEmptyState } from './QuillAuthorizedUrlEmptyState'

type EmptyStateProps = {
    type: AuthorizedUrlListType
    experimentId?: ExperimentIdType | null
    productTourId?: string | null
    actionId?: number | null
    displaySuggestions?: boolean
}

export function EmptyState({
    experimentId,
    productTourId,
    actionId,
    type,
    displaySuggestions = true,
}: EmptyStateProps): JSX.Element | null {
    const logic = authorizedUrlListLogic({
        experimentId: experimentId ?? null,
        productTourId: productTourId ?? null,
        actionId: actionId ?? null,
        type,
    })
    const { urlsKeyed, suggestionsLoading, isAddUrlFormVisible } = useValues(logic)
    const { loadSuggestions } = useActions(logic)
    const quillSurface = useQuillSurface()

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

    // If there are authorized URLs, never display this empty state.
    // If the add URL form is visible, don't show the empty state either.
    const hidden = authorizedURLs.length > 0 || isAddUrlFormVisible
    const showsSuggestions = suggestionURLs.length > 0 && displaySuggestions

    const children = useMemo(() => {
        if (hidden) {
            return null
        }

        if (showsSuggestions) {
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
                            onClick={() => loadSuggestions()}
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
    }, [hidden, showsSuggestions, suggestionsLoading, type, domainOrUrl, loadSuggestions, displaySuggestions])

    if (quillSurface) {
        return hidden ? null : (
            <QuillAuthorizedUrlEmptyState
                type={type}
                domainOrUrl={domainOrUrl}
                showsSuggestions={showsSuggestions}
                displaySuggestions={displaySuggestions}
                suggestionsLoading={suggestionsLoading}
                onFetchSuggestions={loadSuggestions}
            />
        )
    }

    return children ? <div className="border rounded p-4 text-secondary">{children}</div> : null
}
