import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { BatchExportBackfills } from 'scenes/data-pipelines/batch-exports/BatchExportBackfills'
import { BatchExportBackfillsLogicProps } from 'scenes/data-pipelines/batch-exports/batchExportBackfillsLogic'
import { batchExportDataLogic } from 'scenes/data-pipelines/batch-exports/batchExportDataLogic'
import { BatchExportLoadingSkeleton } from 'scenes/data-pipelines/batch-exports/BatchExportLoadingSkeleton'

import { hogFunctionBackfillsLogic } from './hogFunctionBackfillsLogic'

export function HogFunctionBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const logic = hogFunctionBackfillsLogic({ id })
    const { configuration, isReady, enableBackfillsFailed } = useValues(logic)
    const { enableHogFunctionBackfills } = useActions(logic)

    if (enableBackfillsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: enableHogFunctionBackfills,
                    'data-attr': 'hog-function-backfills-enable-retry',
                }}
            >
                Couldn't set up backfills for this destination. If it keeps happening, contact support.
            </LemonBanner>
        )
    }

    if (!isReady) {
        return <BatchExportLoadingSkeleton />
    }

    return (
        <BindLogic logic={batchExportDataLogic} props={{ id: configuration.batch_export_id! }}>
            <div className="flex flex-col gap-3">
                <p className="text-secondary mb-0">
                    Backfills re-run this destination against historical events from a time range you choose.
                </p>
                <BatchExportBackfills id={configuration.batch_export_id!} context="hog_function" />
            </div>
        </BindLogic>
    )
}
