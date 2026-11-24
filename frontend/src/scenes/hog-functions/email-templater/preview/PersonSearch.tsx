import { useActions, useValues } from 'kea'
import { useContext, useState } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { emailPreviewPersonLogic } from './emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from './EmailPreviewScopeContext'

export function PersonSearch({ onDone }: { onDone: () => void }): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { searchResults, searchResultsLoading } = useValues(emailPreviewPersonLogic({ scope }))
    const { setSearch, pickPerson } = useActions(emailPreviewPersonLogic({ scope }))
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
            ) : (
                searchResults.map((person) => (
                    <LemonButton
                        key={person.id}
                        size="small"
                        fullWidth
                        onClick={() => {
                            pickPerson(person)
                            onDone()
                        }}
                    >
                        {person.displayName}
                    </LemonButton>
                ))
            )}
        </div>
    )
}
