import React, { useEffect, useState } from 'react'
import { useValues, useActions } from 'kea'
import { personsLogic } from './personsLogic'
import { IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonInput } from '@posthog/lemon-ui'
import { useDebouncedCallback } from 'use-debounce'

export const PersonsSearch = ({ autoFocus = true }: { autoFocus?: boolean }): JSX.Element => {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { listFilters } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('')

    const loadPersonsDebounced = useDebouncedCallback(loadPersons, 800)

    useEffect(() => {
        setSearchTerm(listFilters.search || '')
    }, [])

    useEffect(() => {
        setListFilters({ search: searchTerm || undefined })
        loadPersonsDebounced()
    }, [searchTerm])

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="search"
                autoFocus={autoFocus}
                placeholder="Search for persons"
                onChange={setSearchTerm}
                value={searchTerm}
                data-attr="persons-search"
            />
            <Tooltip
                title={
                    <>
                        Search by email or Distinct ID. Email will match partially, for example: "@gmail.com". Distinct
                        ID needs to match exactly.
                    </>
                }
            >
                <IconInfo className="text-2xl text-muted-alt shrink-0" />
            </Tooltip>
        </div>
    )
}
