import { useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DestinationModal } from '../../shared/components/DestinationModal'
import { destinationModalLogic } from '../../shared/logics/destinationModalLogic'
import { warehouseDestinationsSceneLogic } from './warehouseDestinationsSceneLogic'
import { WarehouseDestinationsTable } from './WarehouseDestinationsTable'

const MODAL_KEY = 'warehouse-destinations-scene'

export const scene: SceneExport = {
    component: WarehouseDestinationsScene,
    logic: warehouseDestinationsSceneLogic,
}

export function WarehouseDestinationsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { destinations, destinationsLoading, loadError, deletingId, hasSources } = useValues(
        warehouseDestinationsSceneLogic
    )
    const { loadDestinations, deleteDestination, destinationCreated } = useActions(warehouseDestinationsSceneLogic)

    const modalProps = {
        modalKey: MODAL_KEY,
        onSaved: () => loadDestinations(),
        onCreated: (destination: ExternalDataDestinationApi) => destinationCreated(destination),
    }
    const { openForCreate, openForEdit } = useActions(destinationModalLogic(modalProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION]) {
        return <NotFound object="page" caption="Warehouse destinations isn't available for this project yet." />
    }

    const newDestinationButton = (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlusSmall />}
            onClick={openForCreate}
            data-attr="warehouse-destinations-scene-new"
        >
            New destination
        </LemonButton>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Warehouse destinations"
                description="Destinations are where your warehouse sources write the rows they sync. Pick which ones a source or a single table uses from that source's Destinations tab. To export PostHog events to a warehouse, use a batch export."
                resourceType={{ type: 'data_warehouse' }}
                actions={
                    todayRailNav ? (
                        <Button variant="primary" onClick={openForCreate} data-attr="warehouse-destinations-scene-new">
                            <IconPlus />
                            New destination
                        </Button>
                    ) : (
                        newDestinationButton
                    )
                }
            />

            {hasSources === false && (
                <LemonBanner type="info">
                    <div className="flex flex-col gap-2">
                        <span>
                            Destinations receive data synced from warehouse sources, such as Stripe or Postgres. They do
                            not receive your PostHog events. To send events to a warehouse, set up a batch export.
                        </span>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.destinations('batch')}
                                data-attr="warehouse-destinations-no-sources-batch-exports"
                            >
                                Set up a batch export
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.dataWarehouseSourceNew()}
                                data-attr="warehouse-destinations-no-sources-add-source"
                            >
                                Add a warehouse source
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            )}

            {loadError ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: loadDestinations,
                        loading: destinationsLoading,
                        'data-attr': 'warehouse-destinations-scene-retry',
                    }}
                >
                    {loadError}
                </LemonBanner>
            ) : (
                <WarehouseDestinationsTable
                    destinations={destinations ?? []}
                    loading={destinationsLoading || destinations === null}
                    onEdit={openForEdit}
                    onDelete={deleteDestination}
                    deletingId={deletingId}
                    emptyState={
                        <div className="flex flex-col gap-2 items-center py-4">
                            <span>
                                No destinations yet. Your sources write to the PostHog warehouse until you add one.
                            </span>
                            <span className="text-muted">
                                Add a destination here, then turn it on from a <Link to={urls.sources()}>source</Link>.
                            </span>
                            {newDestinationButton}
                        </div>
                    }
                />
            )}

            <DestinationModal {...modalProps} />
        </SceneContent>
    )
}
