import { useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { NODE_TYPE_TAG_SETTINGS, STATUS_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

function OverviewItem({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-secondary">{label}</dt>
            <dd className="mb-0 text-sm">{children}</dd>
        </div>
    )
}

function FreshnessItem({
    isTable,
    isMaterialized,
    lastRunAt,
}: {
    isTable: boolean
    isMaterialized: boolean
    lastRunAt: string | null
}): JSX.Element | null {
    if (isTable) {
        return lastRunAt ? (
            <OverviewItem label="Last synced">
                <TZLabel time={lastRunAt} />
            </OverviewItem>
        ) : null
    }

    if (!isMaterialized) {
        return <OverviewItem label="Materialization">Off</OverviewItem>
    }

    return <OverviewItem label="Last run">{lastRunAt ? <TZLabel time={lastRunAt} /> : 'Not run yet'}</OverviewItem>
}

export function NodeDetailOverview({ id }: { id: string }): JSX.Element | null {
    const { node, isMaterialized, effectiveLastRunAt, effectiveLastRunStatus } = useValues(nodeDetailSceneLogic({ id }))

    if (!node) {
        return null
    }

    const typeTag = NODE_TYPE_TAG_SETTINGS[node.type]
    const isTable = node.type === 'table'

    return (
        <dl className="flex flex-row flex-wrap gap-8 mb-0">
            <OverviewItem label="Type">
                <LemonTag type={typeTag.type}>{typeTag.label}</LemonTag>
            </OverviewItem>

            {effectiveLastRunStatus && (
                <OverviewItem label="Status">
                    <LemonTag type={STATUS_TAG_SETTINGS[effectiveLastRunStatus] ?? 'default'}>
                        {effectiveLastRunStatus}
                    </LemonTag>
                </OverviewItem>
            )}

            <FreshnessItem isTable={isTable} isMaterialized={isMaterialized} lastRunAt={effectiveLastRunAt} />

            {node.created_at && (
                <OverviewItem label="Created">
                    <TZLabel time={node.created_at} />
                </OverviewItem>
            )}
        </dl>
    )
}
