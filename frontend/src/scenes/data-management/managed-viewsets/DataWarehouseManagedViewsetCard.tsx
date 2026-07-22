import { useActions, useValues } from 'kea'

import { IconPiggyBank, IconPullRequest } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'

import { AccessControlLevel, AccessControlResourceType } from '../../../types'
import {
    DataWarehouseManagedViewsetsLogicProps,
    dataWarehouseManagedViewsetsLogic,
} from './dataWarehouseManagedViewsetsLogic'

const VIEWSET_DESCRIPTIONS: Record<
    DataWarehouseManagedViewsetKind,
    { title: string; description: string; docsUrl?: string; configUrl: string; icon: JSX.Element }
> = {
    revenue_analytics: {
        title: 'Revenue analytics',
        description:
            'Track and analyze revenue data from your payment providers and custom events. Automatically creates optimized views for revenue metrics, trends, and customer lifetime value.',
        docsUrl: 'https://posthog.com/docs/revenue-analytics',
        configUrl: '/data-management/revenue',
        icon: <IconPiggyBank className="text-xl" />,
    },
    engineering_analytics: {
        title: 'Engineering analytics',
        description:
            'Analyze pull request and CI workflow health across your connected GitHub repos. Automatically creates optimized views over your engineering activity.',
        configUrl: '/engineering-analytics/overview',
        icon: <IconPullRequest className="text-xl" />,
    },
}

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

    // The backend returns a viewset per enum choice; skip any kind the frontend doesn't yet
    // describe so a newly added backend kind can't crash the whole scene before we catch up.
    const viewset = VIEWSET_DESCRIPTIONS[kind]
    if (!viewset) {
        return null
    }

    const { title, description, docsUrl, configUrl, icon } = viewset
    const isEnabled = currentTeam!.managed_viewsets![kind]
    const isToggling = togglingViewset === kind && toggleResultLoading
    const showDocsLink = displayDocsLink && !!docsUrl

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
                        {showDocsLink && displayConfigLink && <span>|</span>}
                        {showDocsLink && (
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
                                disabledReason={
                                    isToggling ? 'Saving, this might take a few seconds...' : disabledReason
                                }
                                label={
                                    isToggling
                                        ? isEnabled
                                            ? 'Disabling, please wait a moment...'
                                            : 'Enabling, please wait a moment...'
                                        : isEnabled
                                          ? 'Enabled'
                                          : 'Disabled'
                                }
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
