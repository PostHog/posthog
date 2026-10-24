import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { ManagedWarehouseDatasetStatusApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { StatusTag } from './warehouseStatusDisplay'

export function DatasetCard({
    title,
    description,
    icon,
    status,
}: {
    title: string
    description: string
    icon: JSX.Element
    status: ManagedWarehouseDatasetStatusApi
}): JSX.Element {
    const hasProgress = status.total_partitions !== null && status.total_partitions > 0
    const progress = hasProgress ? Math.round((status.completed_partitions / status.total_partitions!) * 100) : null

    return (
        <LemonCard className="p-4 space-y-4" hoverEffect={false}>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                    <div className="text-xl text-muted mt-0.5">{icon}</div>
                    <div>
                        <h3 className="mb-1">{title}</h3>
                        <p className="text-muted mb-0">{description}</p>
                    </div>
                </div>
                <StatusTag readinessState={status.readiness_state} />
            </div>
            <div className="border-t pt-4 space-y-3">
                <p className="mb-0">{status.detail}</p>
                {progress !== null && (
                    <div className="space-y-1">
                        <div className="flex justify-between text-xs text-muted">
                            <span>Historical backfill</span>
                            <span>
                                {status.completed_partitions} / {status.total_partitions}
                            </span>
                        </div>
                        <LemonProgress percent={progress} />
                    </div>
                )}
                {status.current_partition && (
                    <div className="text-xs text-muted">
                        Current partition: <code className="break-all">{status.current_partition}</code>
                    </div>
                )}
                {status.last_updated_at && (
                    <div className="text-xs text-muted">
                        Updated {humanFriendlyDetailedTime(status.last_updated_at)}
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
