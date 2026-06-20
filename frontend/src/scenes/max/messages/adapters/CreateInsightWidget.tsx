import { GenericMcpToolRenderer } from '../../sandbox/components/tool/GenericMcpToolRenderer'
import { SandboxDataToolRow } from '../../sandbox/components/tool/SandboxDataToolRow'
import type { SandboxToolRendererProps } from '../../sandbox/sandboxToolRegistry'
import { VisualizationWidget, getArtifactOpenTarget } from '../VisualizationWidget'
import { extractVisualizationArtifact } from './extractors'

/**
 * Renders insight create / update / read tool calls through `VisualizationWidget`. Until the
 * artifact lands (pending / in-progress / malformed output) we fall back to the generic card so
 * the call still renders something.
 */
export function CreateInsightWidget(props: SandboxToolRendererProps): JSX.Element {
    const { message } = props
    const artifact = message.status === 'completed' ? extractVisualizationArtifact(message) : null

    if (!artifact) {
        return <GenericMcpToolRenderer {...props} />
    }

    const target = getArtifactOpenTarget(artifact.envelope, artifact.content)

    return (
        <SandboxDataToolRow {...props}>
            <VisualizationWidget
                content={artifact.content}
                openUrl={target.url}
                openTooltip={target.tooltip}
                embedded
            />
        </SandboxDataToolRow>
    )
}
