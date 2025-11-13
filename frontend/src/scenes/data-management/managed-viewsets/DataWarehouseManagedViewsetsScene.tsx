import { useActions, useValues } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
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

const RESOURCE_TYPES_MAP: Record<DataWarehouseManagedViewsetKind, AccessControlResourceType> = {
    revenue_analytics: AccessControlResourceType.RevenueAnalytics,
}

export function DataWarehouseManagedViewsetsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { kind, views } = useValues(
        disableDataWarehouseManagedViewsetModalLogic({ type: 'DataWarehouseManagedViewsetsScene' })
    )

    const { loadCurrentTeam } = useActions(teamLogic)

    const managedViewsets = currentTeam!.managed_viewsets!

    const onConfirmDisable = async (): Promise<boolean> => {
        if (!kind) {
            return false
        }

        try {
            await api.dataWarehouseManagedViewsets.toggle(kind, false)
            lemonToast.success(`${VIEWSET_TITLES[kind]} viewset disabled and views deleted successfully`)
            loadCurrentTeam()
            return true
        } catch (error: any) {
            lemonToast.error(`Failed to disable ${kind} viewset: ${error.message || 'Unknown error'}`)
            return false
        }
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Managed viewsets"
                resourceType={{ type: 'managed_viewsets' }}
                description="Configure automatically managed database views for analytics features. These views are created and maintained by PostHog to provide optimized data access."
            />

            <div className="space-y-4">
                {(Object.keys(managedViewsets) as DataWarehouseManagedViewsetKind[]).map((kind) => (
                    <DataWarehouseManagedViewsetCard
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
                        <strong>Important:</strong> Before disabling, make sure no queries, insights, or dashboards are
                        using these views. You can re-enable this viewset later, but views might not be available while
                        they're materializing.
                    </>
                }
                viewsActionText="will be deleted"
                confirmButtonText="Yes, disable and delete views"
            />
        </SceneContent>
    )
}
