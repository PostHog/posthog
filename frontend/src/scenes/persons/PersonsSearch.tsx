import React, { useState, useEffect } from 'react'
import { Input } from 'antd'
import { useValues, useActions } from 'kea'
import { personsLogic } from './personsLogic'
import { IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

export const PersonsSearch = ({ autoFocus = true }: { autoFocus?: boolean }): JSX.Element => {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { listFilters } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('')

    useEffect(() => {
        setSearchTerm(listFilters.search || '')
    }, [])

    return (
        <div className="flex items-center gap-2" style={{ width: 'min(100%, 24rem)' }}>
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
            <Tooltip
                title={
                    <>
                        Search by email or Distinct ID. Email will match partially, for example: "@gmail.com". Distinct
                        ID needs to match exactly.
                    </>
                }
            >
                <IconInfo className="text-2xl text-muted-alt" />
            </Tooltip>
        </div>
    )
}
