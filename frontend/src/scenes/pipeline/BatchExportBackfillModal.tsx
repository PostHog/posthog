import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { teamLogic } from 'scenes/teamLogic'

import { batchExportRunsLogic, BatchExportRunsLogicProps } from './batchExportRunsLogic'

export function BatchExportBackfillModal({ id }: BatchExportRunsLogicProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
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
                {
                    // We will assume any dates selected are in the project's timezone and NOT in the user's local time.
                    // So, if a user of a daily export selects "2024-08-14" they mean "2024-08-14 00:00:00 in their
                    // project's timezone".
                }
                <LemonField name="start_at" label={`Start Date (${timezone})`} className="flex-1">
                    {({ value, onChange }) => (
                        <LemonCalendarSelectInput
                            value={
                                value
                                    ? batchExportConfig
                                        ? batchExportConfig.interval === 'day'
                                            ? value.hour(0).minute(0).second(0)
                                            : value.tz(timezone)
                                        : value
                                    : value
                            }
                            onChange={(date) => {
                                if (date) {
                                    let projectDate = date.tz(timezone, true)

                                    if (batchExportConfig && batchExportConfig.interval === 'day') {
                                        projectDate = projectDate.hour(0).minute(0).second(0)
                                    }

                                    onChange(projectDate)
                                } else {
                                    onChange(date)
                                }
                            }}
                            placeholder="Select start date"
                            granularity={
                                batchExportConfig
                                    ? batchExportConfig.interval === 'hour'
                                        ? 'hour'
                                        : batchExportConfig.interval.endsWith('minutes')
                                        ? 'minute'
                                        : 'day'
                                    : 'day'
                            }
                        />
                    )}
                </LemonField>
                <LemonField name="end_at" label={`End Date (${timezone})`} className="flex-1">
                    {({ value, onChange }) => (
                        <LemonCalendarSelectInput
                            value={
                                value
                                    ? batchExportConfig
                                        ? batchExportConfig.interval === 'day'
                                            ? value.hour(0).minute(0).second(0)
                                            : value.tz(timezone)
                                        : value
                                    : value
                            }
                            onChange={(date) => {
                                if (date) {
                                    let projectDate = date.tz(timezone, true)

                                    if (batchExportConfig && batchExportConfig.interval === 'day') {
                                        projectDate = projectDate.hour(0).minute(0).second(0)
                                    }

                                    onChange(projectDate)
                                } else {
                                    onChange(date)
                                }
                            }}
                            placeholder="Select end date (optional)"
                            granularity={
                                batchExportConfig
                                    ? batchExportConfig.interval === 'hour'
                                        ? 'hour'
                                        : batchExportConfig.interval.endsWith('minutes')
                                        ? 'minute'
                                        : 'day'
                                    : 'day'
                            }
                        />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
