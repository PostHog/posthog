import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { batchExportRunsLogic, BatchExportRunsLogicProps } from './batchExportRunsLogic'

export function BatchExportBackfillModal({ id }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id })

    const { batchExportConfig, isBackfillModalOpen, isBackfillFormSubmitting } = useValues(logic)
    const { closeBackfillModal } = useActions(logic)

    return (
        <LemonModal
            title="Backfill batch export"
            onClose={closeBackfillModal}
            isOpen={isBackfillModalOpen}
            width="30rem"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="batch-export-backfill-cancel"
                        disabledReason={isBackfillFormSubmitting ? 'Please wait...' : undefined}
                        onClick={closeBackfillModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="batch-export-backfill-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="batch-export-backfill-submit"
                        loading={isBackfillFormSubmitting}
                    >
                        Schedule runs
                    </LemonButton>
                </>
            }
        >
            <p>
                Backfilling a batch export will sequentially run all batch periods that fall within the range specified
                below. The runs will export data in <b>{batchExportConfig?.interval}</b> intervals, from the start date
                until the end date is reached.
            </p>
            <Form
                logic={batchExportRunsLogic}
                props={{ id: id } as BatchExportRunsLogicProps}
                formKey="backfillForm"
                id="batch-export-backfill-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <LemonField name="start_at" label="Start Date" className="flex-1">
                    {({ value, onChange }) => (
                        <LemonCalendarSelectInput value={value} onChange={onChange} placeholder="Select start date" />
                    )}
                </LemonField>

                <LemonField name="end_at" label="End date" className="flex-1">
                    {({ value, onChange }) => (
                        <LemonCalendarSelectInput
                            value={value}
                            onChange={onChange}
                            placeholder="Select end date (optional)"
                        />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
