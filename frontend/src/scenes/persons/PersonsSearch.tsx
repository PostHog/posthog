import React, { useState, useEffect } from 'react'
import { Input } from 'antd'
import { useValues, useActions } from 'kea'
import { personsLogic } from './personsLogic'

export const PersonsSearch = ({ autoFocus = true }: { autoFocus?: boolean }): JSX.Element => {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { exampleEmail, listFilters } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('')

    useEffect(() => {
        setSearchTerm(listFilters.search)
    }, [])

    return (
        <Input.Search
            data-attr="persons-search"
            placeholder={`search person by email, name or ID (e.g. ${exampleEmail})`}
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
    )
}
