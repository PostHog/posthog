import { LemonButton, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { dayjs } from 'lib/dayjs'

export interface CalendarSyncBackfillModalProps {
    isOpen: boolean
    startDate: string | null
    endDate: string | null
    dateError: string | null
    isSubmitting: boolean
    onStartDateChange: (date: string | null) => void
    onEndDateChange: (date: string | null) => void
    onSubmit: () => void
    onClose: () => void
}

export function CalendarSyncBackfillModal({
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
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            closable={!isSubmitting}
            title="Backfill Google account"
            description="Sync emails and meetings from the selected dates. You can look back up to one year."
            width={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} disabled={isSubmitting}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        loading={isSubmitting}
                        disabledReason={dateError ?? undefined}
                        data-attr="google-account-backfill-submit"
                    >
                        Start backfill
                    </LemonButton>
                </>
            }
            data-attr="google-account-backfill-modal"
        >
            <div className="@container">
                <div className="grid grid-cols-1 gap-4 @min-[30rem]:grid-cols-2">
                    <div>
                        <LemonLabel className="mb-1">Start date</LemonLabel>
                        <DatePicker
                            value={startDate ? dayjs(startDate) : null}
                            onChange={(date) => onStartDateChange(date?.format('YYYY-MM-DD') ?? null)}
                            granularity="day"
                            selectionPeriod="past"
                            selectionPeriodTimezone="UTC"
                            clearable={false}
                            data-attr="google-account-backfill-start-date"
                        />
                    </div>
                    <div>
                        <LemonLabel className="mb-1">End date</LemonLabel>
                        <DatePicker
                            value={endDate ? dayjs(endDate) : null}
                            onChange={(date) => onEndDateChange(date?.format('YYYY-MM-DD') ?? null)}
                            granularity="day"
                            selectionPeriod="past"
                            selectionPeriodTimezone="UTC"
                            clearable={false}
                            data-attr="google-account-backfill-end-date"
                        />
                    </div>
                </div>
                {dateError ? <p className="mt-2 text-danger text-sm">{dateError}</p> : null}
                <p className="mt-3 mb-0 text-secondary text-sm">Both dates are included. Dates use UTC.</p>
            </div>
        </LemonModal>
    )
}
