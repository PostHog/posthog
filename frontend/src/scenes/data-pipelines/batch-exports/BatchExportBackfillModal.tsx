import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import {
    BatchExportBackfillModalLogicProps,
    batchExportBackfillModalLogic,
    formatDateForDisplay,
    getCalendarGranularity,
    transformDateOnChange,
} from './batchExportBackfillModalLogic'
import { formatHourString } from './utils'

export function BatchExportBackfillModal({ id }: BatchExportBackfillModalLogicProps): JSX.Element {
    const logic = batchExportBackfillModalLogic({ id })

    const {
        batchExportConfig,
        isBackfillModalOpen,
        isBackfillFormSubmitting,
        isEarliestBackfill,
        interval,
        timezone,
        dayOfWeek,
        dayOfWeekName,
        hourOffset,
    } = useValues(logic)
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
                below. The runs will export data in <b>{interval}</b> intervals, from the start date until the end date
                is reached.
            </p>
            {interval === 'day' && hourOffset !== null && (
                <p className="text-sm text-secondary">
                    Your batch export is configured to run at{' '}
                    <b>
                        {formatHourString(hourOffset)} ({timezone}) every day
                    </b>
                    .
                </p>
            )}
            {interval === 'week' && dayOfWeek !== null && hourOffset !== null && (
                <p className="text-sm text-secondary">
                    Your batch export is configured to run at{' '}
                    <b>
                        {formatHourString(hourOffset)} ({timezone}) every week on {dayOfWeekName}
                    </b>
                    .
                </p>
            )}
            <Form
                logic={batchExportBackfillModalLogic}
                props={{ id: id } as BatchExportBackfillModalLogicProps}
                formKey="backfillForm"
                id="batch-export-backfill-form"
                enableFormOnSubmit
                className="flex flex-col gap-2"
            >
                <LemonField name="start_at" label={`Start Date (${timezone})`} className="flex-1">
                    {({ value, onChange }) =>
                        !isEarliestBackfill ? (
                            <LemonCalendarSelectInput
                                value={formatDateForDisplay(value)}
                                onChange={(date) => {
                                    onChange(transformDateOnChange(date, interval, timezone, hourOffset))
                                }}
                                placeholder="Select start date"
                                granularity={getCalendarGranularity(interval)}
                            />
                        ) : (
                            <LemonInput value="Beginning of time" disabled />
                        )
                    }
                </LemonField>

                {batchExportConfig?.model == 'persons' ? (
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
                            value={formatDateForDisplay(value)}
                            onChange={(date) => {
                                onChange(transformDateOnChange(date, interval, timezone, hourOffset))
                            }}
                            placeholder="Select end date"
                            granularity={getCalendarGranularity(interval)}
                        />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
