import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ExternalDataSchemaStatus } from '~/types'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { MarketingSourceStatus, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { StatusIcon } from '../settings/StatusIcon'

export function IntegrationFilter(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { allAvailableSourcesWithStatus, integrationFilter, dataWarehouseSources, isAdPerformance } =
        useValues(marketingAnalyticsLogic)
    const { setIntegrationFilter } = useActions(marketingAnalyticsLogic)
    const [showPopover, setShowPopover] = useState(false)

    const includeOrganic = isAdPerformance && !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]
    const organicSources = includeOrganic
        ? (dataWarehouseSources?.results ?? [])
              .filter((source) => source.source_type === 'GoogleSearchConsole')
              .map((source) => ({
                  id: source.id,
                  name: source.source_type,
                  type: 'native',
                  source_type: source.source_type,
                  prefix: source.description || source.prefix || undefined,
                  status: undefined,
                  statusMessage: undefined,
              }))
        : []
    const availableSources = [...allAvailableSourcesWithStatus, ...organicSources]
    const groups = includeOrganic
        ? [
              { title: 'Ad sources', sources: allAvailableSourcesWithStatus },
              { title: 'Organic search', sources: organicSources },
          ]
        : [{ title: '', sources: availableSources }]
    const selectedIds = (integrationFilter.integrationSourceIds || []).filter((id) =>
        availableSources.some((source) => source.id === id)
    )
    const allSourceIds = availableSources.map((s) => s.id)
    const isAllSelected = selectedIds.length === allSourceIds.length && allSourceIds.length > 0
    const isSomeSelected = selectedIds.length > 0 && selectedIds.length < allSourceIds.length
    // Absent means included, so only an explicit false hides these rows.
    const includeNonIntegrated = integrationFilter.includeNonIntegrated !== false

    const handleToggleAll = (): void => {
        if (isAllSelected || isSomeSelected) {
            setIntegrationFilter({ integrationSourceIds: [], includeNonIntegrated })
        } else {
            setIntegrationFilter({ integrationSourceIds: allSourceIds, includeNonIntegrated })
        }
    }

    const handleToggleSource = (sourceId: string): void => {
        const newIds = selectedIds.includes(sourceId)
            ? selectedIds.filter((id) => id !== sourceId)
            : [...selectedIds, sourceId]

        setIntegrationFilter({ integrationSourceIds: newIds, includeNonIntegrated })
    }

    const handleToggleNonIntegrated = (): void => {
        setIntegrationFilter({ integrationSourceIds: selectedIds, includeNonIntegrated: !includeNonIntegrated })
    }

    const formatSourceLabel = (source: { name: string; type: string; prefix?: string }): string => {
        const prefix = source.prefix ? `${source.prefix} - ` : 'default - '
        return `${prefix}${source.name.replace(/([a-z])([A-Z])/g, '$1 $2')}`
    }

    const displayValue = (): string => {
        // Hiding the non-integrated rows changes what the table reports, so the button says so at
        // every selection, not only when the sources are all in or all out.
        const suffix = includeNonIntegrated ? '' : ', integrated only'
        if (selectedIds.length === 0 || isAllSelected) {
            return includeNonIntegrated ? 'All integrations' : 'Integrated only'
        }
        if (selectedIds.length === 1) {
            const source = availableSources.find((s) => s.id === selectedIds[0])
            return `${source ? formatSourceLabel(source) : '1 integration'}${suffix}`
        }
        return `${selectedIds.length} integrations${suffix}`
    }

    // Don't show the filter if there are no available sources
    if (availableSources.length === 0) {
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
                    {groups
                        .filter((group) => group.sources.length > 0)
                        .map((group) => (
                            <div key={group.title}>
                                {group.title && (
                                    <div className="px-2 py-1 text-xs font-semibold text-secondary">{group.title}</div>
                                )}
                                {group.sources.map((source) => (
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
                                            <SourceIcon type={source.name} size="xsmall" disableTooltip />
                                            <span className="flex-1">{formatSourceLabel(source)}</span>
                                            {/* We don't show the status icon for Completed sources because it would be too many statuses */}
                                            {source.status &&
                                                source.statusMessage &&
                                                source.status !==
                                                    (ExternalDataSchemaStatus.Completed ||
                                                        MarketingSourceStatus.Success) && (
                                                    <StatusIcon status={source.status} message={source.statusMessage} />
                                                )}
                                        </span>
                                    </LemonButton>
                                ))}
                            </div>
                        ))}
                    {!isAdPerformance && (
                        <>
                            <div className="border-t border-border my-1" />
                            <LemonButton
                                fullWidth
                                size="small"
                                onClick={handleToggleNonIntegrated}
                                className="justify-start"
                                tooltip="Traffic no integration reports cost for, like organic, email, or a source you haven't mapped yet."
                            >
                                <span className="flex items-center gap-2">
                                    <LemonCheckbox checked={includeNonIntegrated} className="pointer-events-none" />
                                    <span className="flex-1">No integration</span>
                                </span>
                            </LemonButton>
                        </>
                    )}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconFilter />}
                data-attr="integration-filter"
                className="max-w-full"
            >
                <span className="truncate">{displayValue()}</span>
            </LemonButton>
        </LemonDropdown>
    )
}
