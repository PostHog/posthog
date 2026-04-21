import { BindLogic, useValues } from 'kea'

import { batchExportDataLogic } from 'scenes/data-pipelines/batch-exports/batchExportDataLogic'
import { BatchExportLoadingSkeleton } from 'scenes/data-pipelines/batch-exports/BatchExportLoadingSkeleton'
import { BatchExportRuns } from 'scenes/data-pipelines/batch-exports/BatchExportRuns'

import { hogFunctionBackfillsLogic, HogFunctionBackfillsLogicProps } from '../backfills/hogFunctionBackfillsLogic'

export function HogFunctionRuns({ id }: HogFunctionBackfillsLogicProps): JSX.Element {
    const { configuration, isReady } = useValues(hogFunctionBackfillsLogic({ id }))

    if (!isReady) {
        return <BatchExportLoadingSkeleton />
    }

    return (
        <BindLogic logic={batchExportDataLogic} props={{ id: configuration.batch_export_id! }}>
            <BatchExportRuns id={configuration.batch_export_id!} context="hog_function" />
        </BindLogic>
    )
}
