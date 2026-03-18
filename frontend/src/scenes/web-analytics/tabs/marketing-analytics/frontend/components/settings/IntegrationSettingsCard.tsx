import { useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { IntegrationSettingsModal } from './IntegrationSettingsModal'

export interface IntegrationSettingsCardProps {
    integrationName: string
}

export function IntegrationSettingsCard({ integrationName }: IntegrationSettingsCardProps): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const [isModalOpen, setIsModalOpen] = useState(false)

    // Count configured settings
    const campaignMappings = marketingAnalyticsConfig?.campaign_name_mappings?.[integrationName]
    const customSources = marketingAnalyticsConfig?.custom_source_mappings?.[integrationName]
    const fieldPreference = marketingAnalyticsConfig?.campaign_field_preferences?.[integrationName]

    const mappingsCount = campaignMappings ? Object.keys(campaignMappings).length : 0
    const sourcesCount = customSources ? customSources.length : 0
    const hasFieldPref = !!fieldPreference

    const totalSettings = mappingsCount + sourcesCount + (hasFieldPref ? 1 : 0)
    const hasSettings = totalSettings > 0

    return (
        <>
            <div
                className="group relative border rounded-lg p-4 flex flex-col items-center gap-3 bg-bg-light hover:border-[var(--primary-3000-button-border-hover)] transition-colors cursor-pointer"
                onClick={() => setIsModalOpen(true)}
            >
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <IconGear className="text-muted w-5 h-5" />
                </div>
                <DataWarehouseSourceIcon type={integrationName} size="medium" disableTooltip />
                <div className="text-center">
                    <div className="font-semibold text-sm">{integrationName}</div>
                    {hasSettings ? (
                        <div className="text-xs text-muted mt-1">
                            {mappingsCount > 0 && `${mappingsCount} mapping${mappingsCount !== 1 ? 's' : ''}`}
                            {mappingsCount > 0 && (sourcesCount > 0 || hasFieldPref) && ', '}
                            {sourcesCount > 0 && `${sourcesCount} source${sourcesCount !== 1 ? 's' : ''}`}
                            {sourcesCount > 0 && hasFieldPref && ', '}
                            {hasFieldPref && fieldPreference.match_field}
                        </div>
                    ) : (
                        <div className="text-xs text-muted mt-1">Default configuration</div>
                    )}
                </div>
            </div>
            <IntegrationSettingsModal
                integrationName={integrationName}
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
            />
        </>
    )
}
