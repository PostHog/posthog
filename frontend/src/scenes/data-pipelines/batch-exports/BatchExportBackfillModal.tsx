import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { teamLogic } from 'scenes/teamLogic'

import { batchExportBackfillModalLogic, BatchExportBackfillModalLogicProps } from './batchExportBackfillModalLogic'

export function BatchExportBackfillModal({ id }: BatchExportBackfillModalLogicProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const logic = batchExportBackfillModalLogic({ id })

    const { batchExportConfig, isBackfillModalOpen, isBackfillFormSubmitting, isEarliestBackfill } = useValues(logic)
    const { closeBackfillModal, setEarliestBackfill, unsetEarliestBackfill, setBackfillFormManualErrors } =
        useActions(logic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <LemonModal
            title="Start backfill"
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
                        onClick={() => setBackfillFormManualErrors({})}
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
                logic={batchExportBackfillModalLogic}
                props={{ id: id } as BatchExportBackfillModalLogicProps}
                formKey="backfillForm"
                id="batch-export-backfill-form"
                enableFormOnSubmit
                className="deprecated-space-y-2"
            >
                {
                    // We will assume any dates selected are in the project's timezone and NOT in the user's local time.
                    // So, if a user of a daily export selects "2024-08-14" they mean "2024-08-14 00:00:00 in their
                    // project's timezone".
                }
                <LemonField name="start_at" label={`Start Date (${timezone})`} className="flex-1">
                    {({ value, onChange }) =>
                        !isEarliestBackfill ? (
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
                        ) : (
                            <LemonInput value="Beginning of time" disabled />
                        )
                    }
                </LemonField>

                {batchExportConfig?.model == 'persons' || batchExportConfig?.model == 'sessions' ? (
                    <LemonField name="earliest_backfill">
                        {({ onChange }) => (
                            <LemonCheckbox
                                bordered
                                label={
                                    <span className="flex gap-2 items-center">
                                        Backfill since beginning of time
                                        <Tooltip title="If selected, we will backfill all data since the beginning of time until the end date set below. There is no need to set a start date for the backfill.">
                                            <IconInfo className="text-lg text-secondary" />
                                        </Tooltip>
                                    </span>
                                }
                                onChange={(checked) => {
                                    onChange(checked)
                                    if (checked) {
                                        setEarliestBackfill()
                                    } else {
                                        unsetEarliestBackfill()
                                    }
                                }}
                            />
                        )}
                    </LemonField>
                ) : null}

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
                            placeholder="Select end date"
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
