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
                }}
                enterButton
                onPressEnter={(e) => {
                    e.preventDefault()
                    setListFilters({ search: searchTerm || undefined })
                    loadPersons()
                }}
                allowClear
                onSearch={(value) => {
                    setListFilters({ search: value || undefined })
                    loadPersons()
                }}
                style={{ width: '100%' }}
            />
            <LemonRow
                className="ml-05"
                type="stealth"
                tooltip={
                    <>
                        Search by email or Distinct ID. Email will match partially, for example: "@gmail.com". Distinct
                        ID needs to match exactly.
                    </>
                }
                icon={<IconInfo />}
            />
        </div>
    )
}
