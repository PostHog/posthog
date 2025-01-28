import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'

import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { batchExportBackfillsLogic, BatchExportBackfillsLogicProps } from './batchExportBackfillsLogic'

export function BatchExportBackfills({ id }: BatchExportBackfillsLogicProps): JSX.Element {
    const logic = batchExportBackfillsLogic({ id })
    const { openBackfillModal } = useActions(logic)

    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton type="primary" onClick={() => openBackfillModal()}>
                        Backfill batch export
                    </LemonButton>
                }
            />
            <div className="space-y-2">
                <div>TODO</div>
            </div>
            <BatchExportBackfillModal id={id} />
        </>
    )
}
