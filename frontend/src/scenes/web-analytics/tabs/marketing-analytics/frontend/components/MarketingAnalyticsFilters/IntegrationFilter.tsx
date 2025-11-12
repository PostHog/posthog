import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSchemaStatus } from '~/types'

import { MarketingSourceStatus, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { StatusIcon } from '../settings/StatusIcon'

export function IntegrationFilter(): JSX.Element {
    const { allAvailableSourcesWithStatus, integrationFilter } = useValues(marketingAnalyticsLogic)
    const { setIntegrationFilter } = useActions(marketingAnalyticsLogic)
    const [showPopover, setShowPopover] = useState(false)

    const selectedIds = integrationFilter.integrationSourceIds || []
    const allSourceIds = allAvailableSourcesWithStatus.map((s) => s.id)
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
            const source = allAvailableSourcesWithStatus.find((s) => s.id === selectedIds[0])
            return source ? formatSourceLabel(source) : '1 integration'
        }
        return `${selectedIds.length} integrations`
    }

    // Don't show the filter if there are no available sources
    if (allAvailableSourcesWithStatus.length === 0) {
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
                    {allAvailableSourcesWithStatus.map((source) => (
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
                                <span className="flex-1">{formatSourceLabel(source)}</span>
                                {/* We don't show the status icon for Completed sources because it would be too many statuses */}
                                {source.status &&
                                    source.statusMessage &&
                                    source.status !==
                                        (ExternalDataSchemaStatus.Completed || MarketingSourceStatus.Success) && (
                                        <StatusIcon status={source.status} message={source.statusMessage} />
                                    )}
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
