import { BindLogic, useValues } from 'kea'

import { BatchExportBackfills } from 'scenes/data-pipelines/batch-exports/BatchExportBackfills'
import { BatchExportBackfillsLogicProps } from 'scenes/data-pipelines/batch-exports/batchExportBackfillsLogic'
import { batchExportDataLogic } from 'scenes/data-pipelines/batch-exports/batchExportDataLogic'
import { BatchExportLoadingSkeleton } from 'scenes/data-pipelines/batch-exports/BatchExportLoadingSkeleton'

import { hogFunctionBackfillsLogic } from './hogFunctionBackfillsLogic'

export function HogFunctionBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const { configuration, isReady } = useValues(hogFunctionBackfillsLogic({ id }))

    if (!isReady) {
        return <BatchExportLoadingSkeleton />
    }

    return (
        <BindLogic logic={batchExportDataLogic} props={{ id: configuration.batch_export_id! }}>
            <BatchExportBackfills id={configuration.batch_export_id!} context="hog_function" />
        </BindLogic>
    )
}
