import React, { useState, useEffect } from 'react'
import { Input } from 'antd'
import { useValues, useActions } from 'kea'
import { personsLogic } from './personsLogic'
import { LemonRow } from 'lib/components/LemonRow'
import { IconInfo } from 'lib/components/icons'

export const PersonsSearch = ({ autoFocus = true }: { autoFocus?: boolean }): JSX.Element => {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { listFilters } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('')

    useEffect(() => {
        setSearchTerm(listFilters.search || '')
    }, [])

    return (
        <div style={{ display: 'flex', alignItems: 'center', width: 'min(100%, 24rem)' }}>
            <Input.Search
                data-attr="persons-search"
                placeholder="Search for persons"
                autoFocus={autoFocus}
                value={searchTerm}
                onChange={(e) => {
                    setSearchTerm(e.target.value)
                    if (!e.target.value) {
                        setListFilters({ search: undefined })
                        loadPersons()
                    }
                }}
                enterButton
                allowClear
                onSearch={() => {
                    setListFilters({ search: searchTerm || undefined })
                    loadPersons()
                }}
                style={{ width: '100%' }}
            />
            <LemonRow
                type="stealth"
                tooltip={
                    <>
                        Search by email, name, ID, or even contents of properties. You can also search for persons who
                        just <i>have</i> a property like so: "has:your_property".
                    </>
                }
                icon={<IconInfo />}
            />
        </div>
    )
}
