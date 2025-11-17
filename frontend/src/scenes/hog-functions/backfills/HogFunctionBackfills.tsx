import { className } from '@medv/finder'
import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { BuilderHog3 } from 'lib/components/hedgehogs'
import { cn } from 'lib/utils/css-classes'
import { BatchExportBackfills } from 'scenes/data-pipelines/batch-exports/BatchExportBackfills'
import { BatchExportBackfillsLogicProps } from 'scenes/data-pipelines/batch-exports/batchExportBackfillsLogic'

import { hogFunctionBackfillsLogic } from './hogFunctionBackfillsLogic'

export function HogFunctionBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const logic = hogFunctionBackfillsLogic({ id, service: null })
    const { enableHogFunctionBackfills } = useActions(logic)
    const { batchExportConfig, batchExportConfigLoading } = useValues(logic)

    if (batchExportConfigLoading) {
        return (
            <div className="flex justify-center">
                <Spinner />
            </div>
        )
    }

    if (!batchExportConfig) {
        return (
            <>
                <div
                    className={cn(
                        'border-2 border-dashed border-primary w-full p-8 justify-center rounded mt-2 mb-4',
                        className
                    )}
                >
                    <div className="flex justify-center items-center">
                        <div className="w-40 lg:w-50 mb-4 hidden md:block">
                            <BuilderHog3 className="w-full h-full" />
                        </div>
                        <div className="flex flex-col items-start gap-2">
                            <h2 className="mb-0">No backfills yet</h2>
                            <span className="max-w-72">
                                Destination backfills allow you to backfill historical data to your real-time data
                                destinations configured in PostHog.
                            </span>
                            <LemonButton type="primary" onClick={enableHogFunctionBackfills}>
                                Enable backfills
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </>
        )
    }

    return <BatchExportBackfills id={id} />
}
