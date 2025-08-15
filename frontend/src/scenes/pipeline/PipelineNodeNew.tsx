import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { BatchExportConfiguration } from 'scenes/data-pipelines/batch-exports/BatchExportConfiguration'
import { NewSourceWizardScene } from 'scenes/data-warehouse/new/NewSourceWizard'
import { HogFunctionConfiguration } from 'scenes/hog-functions/configuration/HogFunctionConfiguration'
import { SceneExport } from 'scenes/sceneTypes'

import { AvailableFeature, PipelineStage } from '~/types'

import { DESTINATION_TYPES, SITE_APP_TYPES } from './destinations/constants'
import { NewDestinations } from './destinations/NewDestinations'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { PipelinePluginConfiguration } from './PipelinePluginConfiguration'

const paramsToProps = ({
    params: { stage, id } = {},
    searchParams: { kind } = {},
}: {
    params: { stage?: string; id?: string }
    searchParams?: { kind?: string }
}): PipelineNodeNewLogicProps => {
    const numericId = id && /^\d+$/.test(id) ? parseInt(id) : undefined
    const pluginId = numericId && !isNaN(numericId) ? numericId : null
    const hogFunctionId = pluginId ? null : id?.startsWith('hog-') ? id.slice(4) : null
    const batchExportDestination = hogFunctionId ? null : (id ?? null)

    return {
        stage: PIPELINE_TAB_TO_NODE_STAGE[stage + 's'] || null, // pipeline tab has stage plural here we have singular
        pluginId,
        batchExportDestination,
        hogFunctionId,
        kind: kind ?? null,
    }
}

export const scene: SceneExport = {
    component: PipelineNodeNew,
    logic: pipelineNodeNewLogic,
    paramsToProps,
}

export function PipelineNodeNew(params: { stage?: string; id?: string } = {}): JSX.Element {
    const { stage, pluginId, batchExportDestination, hogFunctionId } = paramsToProps({ params })

    if (!stage) {
        return <NotFound object="pipeline app stage" />
    }

    if (pluginId) {
        const res = <PipelinePluginConfiguration stage={stage} pluginId={pluginId} />
        if (stage === PipelineStage.Destination) {
            return <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>{res}</PayGateMini>
        }
        return res
    }

    if (batchExportDestination) {
        if (stage !== PipelineStage.Destination) {
            return <NotFound object={batchExportDestination} />
        }
        return (
            <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>
                <BatchExportConfiguration service={batchExportDestination} />
            </PayGateMini>
        )
    }

    if (hogFunctionId) {
        return <HogFunctionConfiguration templateId={hogFunctionId} />
    }

    if (stage === PipelineStage.Transformation) {
        return <NewDestinations types={['transformation']} />
    } else if (stage === PipelineStage.Destination) {
        return <NewDestinations types={DESTINATION_TYPES} />
    } else if (stage === PipelineStage.SiteApp) {
        return <NewDestinations types={SITE_APP_TYPES} />
    } else if (stage === PipelineStage.Source) {
        return <NewSourceWizardScene />
    }
    return <NotFound object="pipeline new options" />
}
