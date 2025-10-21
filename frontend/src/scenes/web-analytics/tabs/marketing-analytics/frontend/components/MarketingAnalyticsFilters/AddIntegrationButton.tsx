import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import {
    VALID_NATIVE_MARKETING_SOURCES,
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
} from '../../logic/utils'

export function AddIntegrationButton(): JSX.Element {
    const [showPopover, setShowPopover] = useState(false)

    const groupedIntegrations = {
        native: VALID_NATIVE_MARKETING_SOURCES,
        external: VALID_NON_NATIVE_MARKETING_SOURCES,
        'self-managed': VALID_SELF_MANAGED_MARKETING_SOURCES,
    }

    const handleIntegrateClick = (integrationId: string): void => {
        router.actions.push(urls.dataWarehouseSourceNew(integrationId))

        setShowPopover(false)
    }

    const renderIntegrationGroup = (type: string, integrations: string[], title: string): JSX.Element | null => {
        if (integrations.length === 0) {
            return null
        }

        return (
            <div key={type}>
                <div className="px-2 py-1 text-xs font-medium text-muted-foreground">{title}</div>
                {integrations.map((integrationId) => (
                    <LemonButton
                        key={integrationId}
                        fullWidth
                        size="small"
                        onClick={() => handleIntegrateClick(integrationId)}
                        className="justify-start"
                    >
                        <span className="flex items-center gap-2">
                            <DataWarehouseSourceIcon type={integrationId} size="xsmall" disableTooltip />
                            <span className="flex flex-col items-start">
                                <span className="font-medium">{integrationId}</span>
                            </span>
                        </span>
                    </LemonButton>
                ))}
            </div>
        )
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
                    <div className="px-2 py-1 text-xs text-muted-foreground font-bold">Connect new data source</div>
                    {renderIntegrationGroup('native', groupedIntegrations.native, 'Native integrations')}
                    {renderIntegrationGroup('external', groupedIntegrations.external, 'External sources')}
                    {renderIntegrationGroup(
                        'self-managed',
                        groupedIntegrations['self-managed'],
                        'Self-managed sources'
                    )}
                </div>
            }
        >
            <LemonButton type="primary" size="small" icon={<IconPlusSmall />} data-attr="add-integration">
                Add integration
            </LemonButton>
        </LemonDropdown>
    )
}
