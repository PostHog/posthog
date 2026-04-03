import { useValues } from 'kea'

import { IconDatabase, IconPlug, IconServer } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { DataHealthIssue } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'

import { pipelineStatusSceneLogic } from './pipelineStatusSceneLogic'

const TYPE_CONFIG: { type: DataHealthIssue['type']; label: string; icon: JSX.Element }[] = [
    { type: 'materialized_view', label: 'Materialized views', icon: <IconServer className="size-4" /> },
    { type: 'external_data_sync', label: 'Syncs', icon: <IconDatabase className="size-4" /> },
    { type: 'source', label: 'Sources', icon: <IconDatabase className="size-4" /> },
    { type: 'destination', label: 'Destinations', icon: <IconPlug className="size-4" /> },
    { type: 'transformation', label: 'Transformations', icon: <IconPlug className="size-4" /> },
]

export function PipelineStatusSummary(): JSX.Element {
    const { typeSummary } = useValues(pipelineStatusSceneLogic)

    return (
        <div className="flex flex-wrap gap-3">
            {TYPE_CONFIG.map(({ type, label, icon }) => {
                const count = typeSummary[type] ?? 0
                if (count === 0) {
                    return null
                }
                return (
                    <div key={type} className="flex items-center gap-1.5 text-sm">
                        {icon}
                        <span className="text-muted">{label}</span>
                        <LemonTag type="danger" size="small">
                            {count}
                        </LemonTag>
                    </div>
                )
            })}
        </div>
    )
}
