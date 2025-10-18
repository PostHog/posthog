import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'

export function IntegrationFilter(): JSX.Element {
    const { allAvailableSources, integrationFilter } = useValues(marketingAnalyticsLogic)
    const { setIntegrationFilter } = useActions(marketingAnalyticsLogic)
    const [showPopover, setShowPopover] = useState(false)

    const selectedIds = integrationFilter.integrationSourceIds || []
    const allSourceIds = allAvailableSources.map((s) => s.id)
    const isAllSelected = selectedIds.length === allSourceIds.length && allSourceIds.length > 0
    const isSomeSelected = selectedIds.length > 0 && selectedIds.length < allSourceIds.length

    const handleToggleAll = (): void => {
        if (isAllSelected || isSomeSelected) {
            setIntegrationFilter({ integrationSourceIds: [] })
        } else {
            setIntegrationFilter({ integrationSourceIds: allSourceIds })
        }
    }

    const handleToggleSource = (sourceId: string): void => {
        const newIds = selectedIds.includes(sourceId)
            ? selectedIds.filter((id) => id !== sourceId)
            : [...selectedIds, sourceId]

        setIntegrationFilter({ integrationSourceIds: newIds })
    }

    const formatSourceLabel = (source: { name: string; type: string; prefix?: string }): string => {
        const prefix = source.prefix ? `${source.prefix} - ` : 'default - '
        return `${prefix}${source.name}`
    }

    const displayValue = (): string => {
        if (selectedIds.length === 0 || isAllSelected) {
            return 'All integrations'
        }
        if (selectedIds.length === 1) {
            const source = allAvailableSources.find((s) => s.id === selectedIds[0])
            return source ? formatSourceLabel(source) : '1 integration'
        }
        return `${selectedIds.length} integrations`
    }

    // Don't show the filter if there are no available sources
    if (allAvailableSources.length === 0) {
        return <></>
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <div className="max-w-80 space-y-px p-1">
                    <LemonButton fullWidth size="small" onClick={handleToggleAll} className="justify-start">
                        <span className="flex items-center gap-2">
                            <LemonCheckbox checked={isAllSelected} className="pointer-events-none" />
                            <span className="font-semibold">
                                {isAllSelected || isSomeSelected ? 'Clear all' : 'Select all'}
                            </span>
                        </span>
                    </LemonButton>
                    <div className="border-t border-border my-1" />
                    {allAvailableSources.map((source) => (
                        <LemonButton
                            key={source.id}
                            fullWidth
                            size="small"
                            onClick={() => handleToggleSource(source.id)}
                            className="justify-start"
                        >
                            <span className="flex items-center gap-2">
                                <LemonCheckbox
                                    checked={selectedIds.includes(source.id)}
                                    className="pointer-events-none"
                                />
                                <DataWarehouseSourceIcon type={source.name} size="xsmall" disableTooltip />
                                <span>{formatSourceLabel(source)}</span>
                            </span>
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton type="secondary" size="small" icon={<IconFilter />} data-attr="integration-filter">
                {displayValue()}
            </LemonButton>
        </LemonDropdown>
    )
}
