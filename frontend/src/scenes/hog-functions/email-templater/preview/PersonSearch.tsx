import { useActions, useValues } from 'kea'
import { useContext, useState } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { PreviewPerson, emailPreviewPersonLogic } from './emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from './EmailPreviewScopeContext'

export function PersonSearch({ onPick }: { onPick: (person: PreviewPerson) => void }): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { searchResults, searchResultsLoading, searchFailed } = useValues(emailPreviewPersonLogic({ scope }))
    const { setSearch } = useActions(emailPreviewPersonLogic({ scope }))
    const [search, setSearchValue] = useState('')

    return (
        <div className="flex flex-col gap-1">
            <LemonInput
                type="search"
                size="small"
                placeholder="Search for a person"
                autoFocus
                value={search}
                onChange={(value) => {
                    setSearchValue(value)
                    setSearch(value)
                }}
            />
            {searchResultsLoading ? (
                <Spinner />
            ) : search.trim() && searchFailed ? (
                <span className="text-muted text-xs px-1">Couldn't search people. Try searching again.</span>
            ) : search.trim() && searchResults.length === 0 ? (
                <span className="text-muted text-xs px-1">No one matches this search.</span>
            ) : (
                searchResults.map((person) => (
                    <LemonButton key={person.id} size="small" fullWidth onClick={() => onPick(person)}>
                        {person.displayName}
                    </LemonButton>
                ))
            )}
        </div>
    )
}
