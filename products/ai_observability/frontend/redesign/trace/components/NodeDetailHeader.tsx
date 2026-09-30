import { LemonTag } from '@posthog/lemon-ui'

import { TraceTreeNode } from '../types'
import { NodeKindGlyph } from './NodeKindGlyph'
import { NodeStatChips } from './NodeStatChips'

export interface NodeDetailHeaderProps {
    node: TraceTreeNode
}

export function NodeDetailHeader({ node }: NodeDetailHeaderProps): JSX.Element {
    return (
        <header className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 min-w-0">
                <NodeKindGlyph kind={node.kind} size="medium" />
                <h3 className="m-0 truncate text-base font-semibold">{node.name}</h3>
            </div>
            <div className="flex flex-wrap items-center gap-1">
                <NodeStatChips stats={node.stats} />
                {node.model ? (
                    <LemonTag weight="normal" className="font-mono">
                        {node.model}
                    </LemonTag>
                ) : null}
                {node.hasError ? <LemonTag type="danger">Error</LemonTag> : null}
            </div>
        </header>
    )
}
