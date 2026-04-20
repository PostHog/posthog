import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import {
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
    getEnabledNativeMarketingSources,
} from '../../logic/utils'

interface AddIntegrationButtonProps {
    onIntegrationSelect?: (integrationId: string) => void
}

export function AddIntegrationButton({ onIntegrationSelect }: AddIntegrationButtonProps = {}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [showPopover, setShowPopover] = useState(false)

    const groupedIntegrations = {
        native: getEnabledNativeMarketingSources(featureFlags),
        external: VALID_NON_NATIVE_MARKETING_SOURCES,
        'self-managed': VALID_SELF_MANAGED_MARKETING_SOURCES,
    }

    const handleIntegrateClick = (integrationId: string): void => {
        if (onIntegrationSelect) {
            onIntegrationSelect(integrationId)
        } else {
            router.actions.push(
                urls.dataWarehouseSourceNew(integrationId, urls.marketingAnalyticsApp(), 'Marketing analytics')
            )
        }
        setShowPopover(false)
    }

    const renderIntegrationGroup = (
        type: string,
        integrations: readonly string[],
        title: string
    ): JSX.Element | null => {
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
                        disabledReason={restrictedReason}
                        onClick={() => handleIntegrateClick(integrationId)}
                        className="justify-start"
                    >
                        <span className="flex items-center gap-2">
                            <SourceIcon type={integrationId} size="xsmall" disableTooltip />
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
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlusSmall />}
                data-attr="add-integration"
                disabledReason={restrictedReason}
            >
                Add source
            </LemonButton>
        </LemonDropdown>
    )
}
