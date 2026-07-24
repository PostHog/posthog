import { IconWarning } from '@posthog/icons'

/**
 * Fallback for node types that cannot render for the current viewer — e.g. inline / ad-hoc
 * queries in a publicly shared notebook, which would otherwise POST to
 * `/api/projects/.../query/`, an endpoint sharing tokens cannot reach.
 */
export function UnsupportedNodePlaceholder(): JSX.Element {
    return (
        <div
            className="NotebookNode--unsupported my-2 rounded border border-dashed border-warning bg-warning-highlight p-3"
            data-attr="notebook-unsupported-node"
        >
            <div className="flex items-start gap-2">
                <IconWarning className="text-warning mt-0.5 shrink-0 text-lg" />
                <div className="flex flex-col">
                    <span className="font-medium">Node cannot be rendered</span>
                    <span className="text-secondary text-sm">
                        This node type is not supported in shared notebooks. We are working on supporting it soon!
                    </span>
                </div>
            </div>
        </div>
    )
}
