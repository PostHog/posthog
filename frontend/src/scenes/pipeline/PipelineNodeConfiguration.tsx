import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'

import { HogFunctionConfiguration } from './hogfunctions/HogFunctionConfiguration'
import { PipelineBatchExportConfiguration } from './PipelineBatchExportConfiguration'
import { pipelineNodeLogic } from './pipelineNodeLogic'
import { PipelinePluginConfiguration } from './PipelinePluginConfiguration'
import { PipelineBackend } from './types'

export function PipelineNodeConfiguration(): JSX.Element {
    const { node, stage } = useValues(pipelineNodeLogic)

    if (!stage) {
        return <NotFound object="pipeline app stage" />
    }

    return (
        <div className="space-y-3">
            {node.backend === PipelineBackend.HogFunction ? (
                <HogFunctionConfiguration id={node.id} />
            ) : node.backend === PipelineBackend.Plugin ? (
                <PipelinePluginConfiguration stage={stage} pluginConfigId={node.id} />
            ) : (
                <PipelineBatchExportConfiguration id={node.id} />
            )}
        </div>
    )
}
