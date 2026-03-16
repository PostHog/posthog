import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { NODE_TYPE_TAG_SETTINGS } from './nodeDetailConstants'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailDetails({ id }: { id: string }): JSX.Element | null {
    const { node, effectiveLastRunAt } = useValues(nodeDetailSceneLogic({ id }))

    if (!node) {
        return null
    }

    const tagSettings = NODE_TYPE_TAG_SETTINGS[node.type]

    return (
        <div className="bg-bg-light border rounded p-4 space-y-2">
            <div className="flex items-center gap-2">
                <span className="text-muted text-sm">Type:</span>
                <LemonTag type={tagSettings.type}>{tagSettings.label}</LemonTag>
            </div>
            <div className="flex items-center gap-2">
                <span className="text-muted text-sm">Created:</span>
                {node.created_at ? <TZLabel time={node.created_at} /> : <span className="text-muted">-</span>}
            </div>
            <div className="flex items-center gap-2">
                <span className="text-muted text-sm">Last refreshed:</span>
                {effectiveLastRunAt ? <TZLabel time={effectiveLastRunAt} /> : <span className="text-muted">Never</span>}
            </div>
            {node.dag_id && (
                <div className="flex items-center gap-2">
                    <span className="text-muted text-sm">DAG:</span>
                    <span className="text-muted">{node.dag_id}</span>
                </div>
            )}
        </div>
    )
}
