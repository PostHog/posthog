import { useState } from 'react'

import { LemonModal, LemonTabs } from '@posthog/lemon-ui'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { CampaignFieldPreferencesConfiguration } from './CampaignFieldPreferencesConfiguration'
import { CampaignNameMappingsConfiguration } from './CampaignNameMappingsConfiguration'
import { CustomSourceMappingsConfiguration } from './CustomSourceMappingsConfiguration'

export interface IntegrationSettingsModalProps {
    integrationName: string
    isOpen: boolean
    onClose: () => void
}

export function IntegrationSettingsModal({
    integrationName,
    isOpen,
    onClose,
}: IntegrationSettingsModalProps): JSX.Element {
    const [activeTab, setActiveTab] = useState('field')

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={
                <div className="flex items-center gap-3">
                    <DataWarehouseSourceIcon type={integrationName} size="small" disableTooltip />
                    <span>{integrationName} settings</span>
                </div>
            }
            width={600}
        >
            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    {
                        key: 'field',
                        label: 'Match field',
                        content: (
                            <div className="space-y-3">
                                <p className="text-muted text-sm">
                                    Select whether to match campaigns using the campaign name or campaign ID. This
                                    determines how we link your UTM parameters back to the {integrationName} data. If
                                    your UTM campaign values don't match either,{' '}
                                    <button
                                        type="button"
                                        className="text-link font-semibold cursor-pointer"
                                        onClick={() => setActiveTab('mappings')}
                                    >
                                        configure manual mappings
                                    </button>
                                    .
                                </p>
                                <CampaignFieldPreferencesConfiguration sourceFilter={integrationName} />
                            </div>
                        ),
                    },
                    {
                        key: 'mappings',
                        label: 'Campaign mappings',
                        content: (
                            <div className="space-y-3">
                                <p className="text-muted text-sm">
                                    If you're using custom UTM campaign values that don't match your {integrationName}{' '}
                                    campaign names or IDs, add mappings here. This lets you manually link arbitrary UTM
                                    campaign tags back to the correct campaign in {integrationName} based on your{' '}
                                    <button
                                        type="button"
                                        className="text-link font-semibold cursor-pointer"
                                        onClick={() => setActiveTab('field')}
                                    >
                                        selected match field
                                    </button>
                                    .
                                </p>
                                <CampaignNameMappingsConfiguration sourceFilter={integrationName} compact />
                            </div>
                        ),
                    },
                    {
                        key: 'sources',
                        label: 'Custom sources',
                        content: (
                            <div className="space-y-3">
                                <p className="text-muted text-sm">
                                    We automatically recognize common UTM sources for {integrationName}, but if you use
                                    custom source values in your campaigns, add them here so we can properly attribute
                                    the traffic.
                                </p>
                                <CustomSourceMappingsConfiguration sourceFilter={integrationName} compact />
                            </div>
                        ),
                    },
                ]}
            />
        </LemonModal>
    )
}
