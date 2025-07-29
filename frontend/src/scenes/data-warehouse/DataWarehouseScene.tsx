import { SceneExport } from 'scenes/sceneTypes'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'

export const scene: SceneExport = {
    component: DataWarehouseScene,
}

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        // redirect to the already existing 404 page
        return <NotFound object="Data Warehouse" />
    }
    return (
        <div>
            <div className="mb-6">
                <h1 className="text-2xl font-semibold">Data Warehouse</h1>
                <p className="text-muted">Manage your data warehouse sources and queries</p>
            </div>
            <div className="space-y-4 p-4">
                <div className="bg-bg-light rounded-lg p-6">
                    <h2 className="text-lg font-semibold mb-4">Data Warehouse Overview</h2>
                    <p className="text-muted">
                        This is the Data Warehouse scene. Here you can manage your data warehouse sources, create
                        queries, and explore your data.
                    </p>
                    <div className="mt-4">
                        <p className="text-sm text-muted">Features coming soon:</p>
                        <ul className="list-disc list-inside mt-2 text-sm text-muted">
                            <li>Data source management</li>
                            <li>Cost estimates</li>
                            <li>Materialized views</li>
                            <li>Data exploration</li>
                            <li>Recent Activity</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    )
}
