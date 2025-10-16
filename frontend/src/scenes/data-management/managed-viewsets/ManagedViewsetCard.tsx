import { useActions, useValues } from 'kea'

import { IconPiggyBank } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { teamLogic } from 'scenes/teamLogic'

import { ManagedViewsetKind } from '~/queries/schema/schema-general'

import { AccessControlLevel, AccessControlResourceType } from '../../../types'
import { ManagedViewsetsLogicProps, managedViewsetsLogic } from './managedViewsetsLogic'

const VIEWSET_DESCRIPTIONS: Record<
    ManagedViewsetKind,
    { title: string; description: string; docsUrl: string; configUrl: string; icon: JSX.Element }
> = {
    revenue_analytics: {
        title: 'Revenue Analytics',
        description:
            'Track and analyze revenue data from your payment providers and custom events. Automatically creates optimized views for revenue metrics, trends, and customer lifetime value.',
        docsUrl: 'https://posthog.com/docs/revenue-analytics',
        configUrl: '/data-management/revenue',
        icon: <IconPiggyBank className="text-xl" />,
    },
}

export interface ManagedViewsetCardProps {
    type: ManagedViewsetsLogicProps['type']
    kind: ManagedViewsetKind
    resourceType: AccessControlResourceType
    displayDocsLink?: boolean
    displayConfigLink?: boolean
}

export function ManagedViewsetCard({
    type,
    kind,
    resourceType,
    displayDocsLink = true,
    displayConfigLink = true,
}: ManagedViewsetCardProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { toggleViewset } = useActions(managedViewsetsLogic({ type }))
    const { togglingViewset, toggleResultLoading } = useValues(managedViewsetsLogic({ type }))

    const { title, description, docsUrl, configUrl, icon } = VIEWSET_DESCRIPTIONS[kind]
    const isEnabled = currentTeam!.managed_viewsets![kind]
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
                    <LemonSwitch
                        checked={isEnabled}
                        onChange={(enabled) => toggleViewset(kind, enabled)}
                        disabled={isToggling}
                        label={isEnabled ? 'Enabled' : 'Disabled'}
                        bordered
                    />
                </AccessControlAction>
            </div>
        </div>
    )
}
