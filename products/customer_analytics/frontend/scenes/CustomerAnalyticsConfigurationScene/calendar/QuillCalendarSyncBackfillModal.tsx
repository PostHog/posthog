import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Text,
} from '@posthog/quill'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { dayjs } from 'lib/dayjs'

import type { CalendarSyncBackfillModalProps } from './CalendarSyncBackfillModal'

export function QuillCalendarSyncBackfillModal({
    isOpen,
    startDate,
    endDate,
    dateError,
    isSubmitting,
    onStartDateChange,
    onEndDateChange,
    onSubmit,
    onClose,
}: CalendarSyncBackfillModalProps): JSX.Element {
    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open && !isSubmitting) {
                    onClose()
                }
            }}
        >
            <DialogContent
                className="sm:max-w-140"
                showCloseButton={!isSubmitting}
                data-attr="google-account-backfill-modal"
            >
                <DialogHeader>
                    <DialogTitle>Backfill Google account</DialogTitle>
                    <DialogDescription>
                        Sync emails and meetings from the selected dates. You can look back up to one year.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="@container flex flex-col gap-3">
                        <div className="grid grid-cols-1 gap-4 @min-[30rem]:grid-cols-2">
                            <Field>
                                <FieldLabel>Start date</FieldLabel>
                                <DatePicker
                                    value={startDate ? dayjs(startDate) : null}
                                    onChange={(date) => onStartDateChange(date?.format('YYYY-MM-DD') ?? null)}
                                    granularity="day"
                                    selectionPeriod="past"
                                    selectionPeriodTimezone="UTC"
                                    clearable={false}
                                    data-attr="google-account-backfill-start-date"
                                />
                            </Field>
                            <Field>
                                <FieldLabel>End date</FieldLabel>
                                <DatePicker
                                    value={endDate ? dayjs(endDate) : null}
                                    onChange={(date) => onEndDateChange(date?.format('YYYY-MM-DD') ?? null)}
                                    granularity="day"
                                    selectionPeriod="past"
                                    selectionPeriodTimezone="UTC"
                                    clearable={false}
                                    data-attr="google-account-backfill-end-date"
                                />
                            </Field>
                        </div>
                        {dateError ? <FieldError>{dateError}</FieldError> : null}
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Both dates are included. Dates use UTC.
                        </Text>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSubmit}
                        loading={isSubmitting}
                        disabledReason={dateError ?? undefined}
                        data-attr="google-account-backfill-submit"
                    >
                        Start backfill
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
