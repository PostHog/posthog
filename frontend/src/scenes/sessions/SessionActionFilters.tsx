import React, { useMemo, useRef, useState } from 'react'
import { Button } from 'antd'
import { EntityWithProperties } from '~/types'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { DownOutlined } from '@ant-design/icons'
import { ActionFilterDropdown } from 'scenes/insights/ActionFilter/ActionFilterDropdown'
import { CloseButton } from 'lib/components/CloseButton'
import { PropertyFilters } from 'lib/components/PropertyFilters'

interface Props {
    actionFilter: EntityWithProperties | null
    updateActionFilter: (update: EntityWithProperties | null) => void
}

export function SessionActionFilters({ actionFilter, updateActionFilter }: Props): JSX.Element {
    const actionFilterButtonRef = useRef<HTMLElement>(null)
    const [actionFilterOpen, setActionFilterOpen] = useState(false)
    const entityLogic = useMemo(
        () =>
            entityFilterLogic({
                setFilters: (_: any, rawFilters: any) => {
                    updateActionFilter(rawFilters[0])
                    setActionFilterOpen(false)
                },
                filters: actionFilter
                    ? [{ actions: [{ filter: actionFilter, order: 0, type: actionFilter.type }] }]
                    : [],
                typeKey: 'sessions-list',
                singleMode: true,
            }),
        []
    )

    return (
        <>
            <div style={{ marginBottom: 8, width: 233 }}>
                <Button
                    data-attr="sessions-filter-action"
                    ref={actionFilterButtonRef}
                    onClick={() => setActionFilterOpen(!actionFilterOpen)}
                    className="ant-btn"
                >
                    {actionFilter?.name || <span style={{ color: '#bfbfbf' }}>Select action to filter by</span>}
                    <DownOutlined style={{ fontSize: 12, color: '#bfbfbf' }} />
                </Button>
                <ActionFilterDropdown
                    open={actionFilterOpen}
                    logic={entityLogic}
                    openButtonRef={actionFilterButtonRef}
                    onClose={() => setActionFilterOpen(false)}
                />
                {actionFilter && (
                    <CloseButton
                        onClick={() => updateActionFilter(null)}
                        style={{
                            float: 'none',
                            marginLeft: 4,
                        }}
                    />
                )}
            </div>
            {actionFilter && (
                <div style={{ marginLeft: 16 }}>
                    <PropertyFilters
                        pageKey={'sessions-action-filter'}
                        onChange={(properties: any) => updateActionFilter({ ...actionFilter, properties })}
                    />
                </div>
            )}
        </>
    )
}
