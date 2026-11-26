import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'

import { AccessControlLevel, AccessControlResourceType } from '../../../types'
import {
    DataWarehouseManagedViewsetsLogicProps,
    dataWarehouseManagedViewsetsLogic,
} from './dataWarehouseManagedViewsetsLogic'
import { VIEWSET_DESCRIPTIONS, VIEWSET_TOGGLING_REASON, viewsetToggleLabel } from './managedViewsetCardContent'

export interface DataWarehouseManagedViewsetCardProps {
    type: DataWarehouseManagedViewsetsLogicProps['type']
    kind: DataWarehouseManagedViewsetKind
    resourceType: AccessControlResourceType
    displayDocsLink?: boolean
    displayConfigLink?: boolean
}

export function DataWarehouseManagedViewsetCard({
    type,
    kind,
    resourceType,
    displayDocsLink = true,
    displayConfigLink = true,
}: DataWarehouseManagedViewsetCardProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { toggleViewset } = useActions(dataWarehouseManagedViewsetsLogic({ type }))
    const { togglingViewset, toggleResultLoading } = useValues(dataWarehouseManagedViewsetsLogic({ type }))

    const viewsetInfo = VIEWSET_DESCRIPTIONS[kind]

    if (!viewsetInfo) {
        return null
    }

    const { title, description, docsUrl, configUrl, icon } = viewsetInfo
    const isEnabled = !!currentTeam?.managed_viewsets?.[kind]
    const isToggling = togglingViewset === kind && toggleResultLoading

    return (
        <div className="border rounded p-4">
            <div className="flex items-center justify-between gap-4">
                <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                        {icon}
                        <h3 className="font-semibold text-lg mb-0">{title}</h3>
                    </div>
                    <p className="text-muted mb-2">{description}</p>
                    <div className="flex items-center gap-2">
                        {displayConfigLink && (
                            <Link to={configUrl} className="text-sm">
                                Configure
                            </Link>
                        )}
                        {displayDocsLink && displayConfigLink && <span>|</span>}
                        {displayDocsLink && (
                            <Link to={docsUrl} target="_blank" className="text-sm">
                                Learn more in the docs
                            </Link>
                        )}
                    </div>
                </div>

                <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                    {({ disabledReason }) => (
                        <div className="flex flex-col gap-2 flex-start items-start">
                            <LemonSwitch
                                checked={isEnabled}
                                onChange={(enabled) => toggleViewset(kind, enabled)}
                                disabledReason={isToggling ? VIEWSET_TOGGLING_REASON : disabledReason}
                                label={viewsetToggleLabel(isToggling, isEnabled)}
                                bordered
                                data-attr="managed-viewset-toggle"
                            />
                        </div>
                    )}
                </AccessControlAction>
            </div>
        </div>
    )
}
