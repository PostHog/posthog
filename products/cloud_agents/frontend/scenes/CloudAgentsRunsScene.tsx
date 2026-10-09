import { useActions, useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { CloudAgentsSceneShell } from '../components/CloudAgentsSceneShell'
import { LoadErrorBanner } from '../components/LoadErrorBanner'
import { NewRunButton } from '../components/NewRunButton'
import { NewRunModal } from '../components/NewRunModal'
import { RunsFilters } from '../components/RunsFilters'
import { RunsTable } from '../components/RunsTable'
import { cloudAgentsEmptyState } from '../emptyState/cloudAgentsEmptyState'
import { cloudAgentsRunsLogic } from '../logics/cloudAgentsRunsLogic'
import { CloudAgentsSceneLogicProps, cloudAgentsSceneLogic } from '../logics/cloudAgentsSceneLogic'

export const scene: SceneExport<CloudAgentsSceneLogicProps> = {
    component: CloudAgentsRunsScene,
    logic: cloudAgentsSceneLogic,
    paramsToProps: () => ({ scene: 'runs' }),
    productKey: ProductKey.CLOUD_AGENTS,
    emptyState: cloudAgentsEmptyState,
}

export function CloudAgentsRunsScene(): JSX.Element {
    const { runsLoadFailed, runsPageLoading } = useValues(cloudAgentsRunsLogic)
    const { loadRuns } = useActions(cloudAgentsRunsLogic)

    return (
        <CloudAgentsSceneShell activeTab="runs" actions={<NewRunButton />}>
            <RunsFilters />
            {runsLoadFailed ? (
                <LoadErrorBanner what="the runs" onRetry={loadRuns} retrying={runsPageLoading} />
            ) : (
                <RunsTable />
            )}
            <NewRunModal />
        </CloudAgentsSceneShell>
    )
}
