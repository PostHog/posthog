import { useActions } from 'kea'

import { IconSearch } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { COMMAND_K_INPUT_ID } from './CommandKSearchInput'
import { commandKSearchLogic } from './commandKSearchLogic'

/** Shown when a filtered search finds nothing. PostHog AI ignores filters, so it is not offered here. */
export function CommandKSearchNoResults(): JSX.Element {
    const { clearQuery } = useActions(commandKSearchLogic)

    return (
        <Empty className="py-8" data-attr="command-k-no-results">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconSearch />
                </EmptyMedia>
                <EmptyTitle>No results</EmptyTitle>
                <EmptyDescription>Nothing matches these filters. Change them, or clear the search.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="outline"
                    size="sm"
                    data-attr="command-k-no-results-clear"
                    onClick={() => {
                        clearQuery('no-results')
                        document.getElementById(COMMAND_K_INPUT_ID)?.focus()
                    }}
                >
                    Clear search
                </Button>
            </EmptyContent>
        </Empty>
    )
}
