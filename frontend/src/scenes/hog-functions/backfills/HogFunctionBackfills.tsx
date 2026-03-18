import { BindLogic, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { BatchExportBackfills } from 'scenes/data-pipelines/batch-exports/BatchExportBackfills'
import {
    BatchExportBackfillsLogicProps,
    batchExportBackfillsLogic,
} from 'scenes/data-pipelines/batch-exports/batchExportBackfillsLogic'

import { hogFunctionBackfillsLogic } from './hogFunctionBackfillsLogic'

export function HogFunctionBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const { configuration, isReady } = useValues(hogFunctionBackfillsLogic({ id }))

    if (!isReady) {
        return (
            <div className="space-y-4">
                <div className="flex justify-between items-center">
                    <LemonSkeleton className="w-20 h-8" fade />
                    <LemonSkeleton className="w-32 h-10" fade />
                </div>
                <LemonSkeleton className="w-full h-96" fade />
            </div>
        )
    }

    return (
        <BindLogic logic={batchExportBackfillsLogic} props={{ id: configuration.batch_export_id! }}>
            <BackfillsWithLoadingCheck batchExportId={configuration.batch_export_id!} />
        </BindLogic>
    )
}

function BackfillsWithLoadingCheck({ batchExportId }: { batchExportId: string }): JSX.Element {
    const { batchExportConfig } = useValues(batchExportBackfillsLogic({ id: batchExportId }))

    if (!batchExportConfig) {
        return (
            <div className="space-y-4">
                <div className="flex justify-between items-center">
                    <LemonSkeleton className="w-20 h-8" fade />
                    <LemonSkeleton className="w-32 h-10" fade />
                </div>
                <LemonSkeleton className="w-full h-96" fade />
            </div>
        )
    }

    return <BatchExportBackfills id={batchExportId} />
}
