import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { batchExportLogic } from './batchExportLogic'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonBanner } from '@posthog/lemon-ui'

export function BatchExportBackfillModal(): JSX.Element {
    const { batchExportConfig, isBackfillModalOpen, isBackfillFormSubmitting } = useValues(batchExportLogic)
    const { closeBackfillModal } = useActions(batchExportLogic)

    return (
        <LemonModal
            title="Export historical data"
            onClose={closeBackfillModal}
            isOpen={isBackfillModalOpen}
            width={'30rem'}
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
                Triggering a historic export will create multiple runs, one after another for the range specified below.
                The runs will export data in <b>{batchExportConfig?.interval}</b> intervals, from the start date until
                the end date is reached.
            </p>

            <Form
                logic={batchExportLogic}
                formKey="backfillForm"
                id="batch-export-backfill-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <LemonBanner type="warning">
                    Exporting historical data beyond 1 month is not recommended. We are actively working on increasing
                    this limit.
                </LemonBanner>

                <Field name="start_at" label="Start Date" className="flex-1">
                    {({ value, onChange }) => (
                        <LemonCalendarSelectInput value={value} onChange={onChange} placeholder="Select start date" />
                    )}
                </Field>

                <Field name="end_at" label="End date" className="flex-1">
                    {({ value, onChange }) => (
                        <LemonCalendarSelectInput
                            value={value}
                            onChange={onChange}
                            placeholder="Select end date (optional)"
                        />
                    )}
                </Field>
            </Form>
        </LemonModal>
    )
}
