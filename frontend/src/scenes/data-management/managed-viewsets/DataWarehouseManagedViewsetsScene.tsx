import { useActions, useValues } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'
import { Text } from '@posthog/quill'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'
import { AccessControlResourceType } from '~/types'

import { DataWarehouseManagedViewsetCard } from './DataWarehouseManagedViewsetCard'
import { DataWarehouseManagedViewsetImpactModal } from './DataWarehouseManagedViewsetImpactModal'
import {
    VIEWSET_TITLES,
    disableDataWarehouseManagedViewsetModalLogic,
} from './disableDataWarehouseManagedViewsetModalLogic'
import { QuillDataWarehouseManagedViewsetCard } from './QuillDataWarehouseManagedViewsetCard'

const PRODUCT_TITLE = 'Managed viewsets'
const PRODUCT_DESCRIPTION =
    'Configure automatically managed database views for analytics features. These views are created and maintained by PostHog to provide optimized data access.'

const UPCOMING_MESSAGE =
    'Managed viewsets is an upcoming feature. It will be available as part of a future product release.'

const RESOURCE_TYPES_MAP: Record<DataWarehouseManagedViewsetKind, AccessControlResourceType> = {
    revenue_analytics: AccessControlResourceType.RevenueAnalytics,
}

export function DataWarehouseManagedViewsetsScene(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { kind, views } = useValues(
        disableDataWarehouseManagedViewsetModalLogic({ type: 'DataWarehouseManagedViewsetsScene' })
    )

    const { loadCurrentTeam } = useActions(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name={PRODUCT_TITLE}
                    resourceType={{ type: 'managed_viewsets' }}
                    description={PRODUCT_DESCRIPTION}
                />
                {todayRailNav ? (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {UPCOMING_MESSAGE}
                    </Text>
                ) : (
                    <p className="text-secondary">{UPCOMING_MESSAGE}</p>
                )}
            </SceneContent>
        )
    }

    if (!currentTeam) {
        return null
    }

    const managedViewsets = currentTeam.managed_viewsets ?? {}

    const onConfirmDisable = async (): Promise<boolean> => {
        if (!kind) {
            return false
        }

        try {
            await api.dataWarehouseManagedViewsets.toggle(kind, false)
            if (kind === 'revenue_analytics') {
                await api.revenueAnalyticsJoins.sync(false)
            }
            lemonToast.success(`${VIEWSET_TITLES[kind]} viewset disabled and views deleted successfully`)
            loadCurrentTeam()
            return true
        } catch (error: any) {
            lemonToast.error(`Failed to disable ${kind} viewset: ${error.message || 'Unknown error'}`)
            return false
        }
    }

    const ViewsetCard = todayRailNav ? QuillDataWarehouseManagedViewsetCard : DataWarehouseManagedViewsetCard

    return (
        <QuillSurfaceContext.Provider value={todayRailNav}>
            <SceneContent>
                <SceneTitleSection
                    name={PRODUCT_TITLE}
                    resourceType={{ type: 'managed_viewsets' }}
                    description={PRODUCT_DESCRIPTION}
                />

                <div className={todayRailNav ? 'flex flex-col gap-4' : 'space-y-4'}>
                    {(Object.keys(managedViewsets) as DataWarehouseManagedViewsetKind[])
                        .filter((kind) => kind in RESOURCE_TYPES_MAP)
                        .map((kind) => (
                            <ViewsetCard
                                key={kind}
                                resourceType={RESOURCE_TYPES_MAP[kind]}
                                type="DataWarehouseManagedViewsetsScene"
                                kind={kind}
                            />
                        ))}
                </div>

                <DataWarehouseManagedViewsetImpactModal
                    type="DataWarehouseManagedViewsetsScene"
                    title={`Disable ${kind ? VIEWSET_TITLES[kind] : ''} viewset?`}
                    action={onConfirmDisable}
                    confirmText={kind || ''}
                    views={views}
                    warningItems={[
                        'Permanently delete all views created by this managed viewset',
                        'Break any existing queries, insights, or dashboards that reference these views',
                        'Stop all scheduled materialization jobs for these views',
                    ]}
                    infoMessage={
                        <>
                            <strong>Important:</strong> Before disabling, make sure no queries, insights, or dashboards
                            are using these views. You can re-enable this viewset later, but views might not be
                            available while they're materializing.
                        </>
                    }
                    viewsActionText="will be deleted"
                    confirmButtonText="Yes, disable and delete views"
                />
            </SceneContent>
        </QuillSurfaceContext.Provider>
    )
}
