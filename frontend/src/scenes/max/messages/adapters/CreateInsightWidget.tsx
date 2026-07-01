import { GenericMcpToolRenderer, DataToolRow, type ToolRendererProps } from 'products/posthog_ai/frontend/api/tools'

import { VisualizationWidget, getArtifactOpenTarget } from '../VisualizationWidget'
import { extractVisualizationArtifact } from './extractors'

/**
 * Renders insight create / update / read tool calls through `VisualizationWidget`. Until the
 * artifact lands (pending / in-progress / malformed output) we fall back to the generic card so
 * the call still renders something.
 */
export function CreateInsightWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const artifact = message.status === 'completed' ? extractVisualizationArtifact(message) : null

    if (!artifact) {
        return <GenericMcpToolRenderer {...props} />
    }

    const target = getArtifactOpenTarget(artifact.envelope, artifact.content)

    return (
        <DataToolRow {...props}>
            <VisualizationWidget
                content={artifact.content}
                openUrl={target.url}
                openTooltip={target.tooltip}
                embedded
            />
        </DataToolRow>
    )
}
