import { IconRefresh } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemTitle, Text } from '@posthog/quill'

import { AuthorizedUrlListType } from './authorizedUrlListLogic'

export function QuillAuthorizedUrlEmptyState({
    type,
    domainOrUrl,
    showsSuggestions,
    displaySuggestions,
    suggestionsLoading,
    onFetchSuggestions,
}: {
    type: AuthorizedUrlListType
    domainOrUrl: string
    showsSuggestions: boolean
    displaySuggestions: boolean
    suggestionsLoading: boolean
    onFetchSuggestions: () => void
}): JSX.Element {
    const isRecordingDomains = type === AuthorizedUrlListType.RECORDING_DOMAINS
    const usage = (
        <>
            It'll allow you to use these in{' '}
            {isRecordingDomains ? (
                <span>recordings.</span>
            ) : (
                <span>web analytics, web experiments and our toolbar.</span>
            )}
        </>
    )
    const allDomainsNote = isRecordingDomains ? (
        <span>When no domains are specified, recordings will be authorized on all domains.</span>
    ) : null

    if (showsSuggestions) {
        return (
            <Item variant="outline" size="sm">
                <ItemContent>
                    <ItemTitle>{`There are no authorized ${domainOrUrl}s.`}</ItemTitle>
                    <ItemDescription>
                        We've found some URLs you've used PostHog from in the last 3 days. Consider authorizing them.{' '}
                        {usage} {allDomainsNote}
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <Item variant="outline" size="sm">
            <ItemContent>
                <ItemTitle>{`There are no authorized ${domainOrUrl}s.`}</ItemTitle>
                <ItemDescription>
                    Add one to get started. When you send us events we'll suggest the ones that you should authorize.{' '}
                    {usage} {allDomainsNote}
                </ItemDescription>
            </ItemContent>
            {displaySuggestions && (
                <ItemActions className="flex-col items-end">
                    <Button
                        variant="outline"
                        onClick={() => onFetchSuggestions()}
                        loading={suggestionsLoading}
                        data-attr="authorized-url-list-fetch-suggestions"
                    >
                        <IconRefresh />
                        Fetch suggestions
                    </Button>
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        Sent an event? Refetch suggestions.
                    </Text>
                </ItemActions>
            )}
        </Item>
    )
}
