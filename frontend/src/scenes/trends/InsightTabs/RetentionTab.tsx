import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined } from '@ant-design/icons'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'

export function RetentionTab(): JSX.Element {
    const node = useRef()
    const [open, setOpen] = useState<boolean>(false)
    const { filters, startEntity } = useValues(retentionTableLogic)
    const { setFilters } = useActions(retentionTableLogic)

    const entityLogic = entityFilterLogic({
        setFilters: (filters) => {
            setFilters(filters)
            setOpen(false)
        },
        filters: filters,
        typeKey: 'retention-table',
        singleMode: true,
    })

    return (
        <>
            <h4 className="secondary">Target Event</h4>
            <button
                ref={node}
                className="filter-action btn btn-sm btn-light"
                type="button"
                onClick={(): void => setOpen(!open)}
                style={{
                    fontWeight: 500,
                }}
            >
                {startEntity?.name || 'Select action'}
                <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />
            </button>
            {open && (
                <ActionFilterDropdown
                    logic={entityLogic}
                    onClickOutside={(e): void => {
                        if (node.current.contains(e.target)) {
                            return
                        }
                        setOpen(false)
                    }}
                />
            )}
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="insight-retention" />
        </>
    )
}
