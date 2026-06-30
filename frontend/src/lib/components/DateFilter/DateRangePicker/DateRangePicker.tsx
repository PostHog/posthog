import './DateRangePicker.scss'

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar, IconClock } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Popover } from '@posthog/lemon-ui'

import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { DateOption } from 'lib/components/DateFilter/rollingDateRangeFilterLogic'
import { TimezoneSelect } from 'lib/components/TimezoneSelect'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { DateRange } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

import { DEFAULT_DATE_RANGE_PICKER_OPTIONS } from './constants'
import { dateRangePickerLogic } from './dateRangePickerLogic'
import { DATE_TIME_FORMAT, formatDateRangeLabel, getShortLabel, parseDateExpression } from './utils'

interface DateTimeInputProps {
    value: string
    onChange: (value: string) => void
    placeholder: string
    timezone: string
    label: string
}

const DateTimeInput = ({ value, onChange, placeholder, timezone, label }: DateTimeInputProps): JSX.Element => {
    const [calendarOpen, setCalendarOpen] = useState(false)

    const parsedValue = parseDateExpression(value, timezone)

    const handleCalendarSelect = (date: dayjs.Dayjs): void => {
        onChange(date.format(DATE_TIME_FORMAT))
        setCalendarOpen(false)
    }

    return (
        <div className="flex-1">
            <div className="text-xs text-secondary mb-1">{label}</div>
            <Popover
                visible={calendarOpen}
                onClickOutside={() => setCalendarOpen(false)}
                placement="bottom-start"
                overlay={
                    <LemonCalendarSelect
                        value={parsedValue}
                        onChange={handleCalendarSelect}
                        onClose={() => setCalendarOpen(false)}
                        granularity="minute"
                        use24HourFormat
                    />
                }
            >
                <LemonInput
                    value={value}
                    onChange={onChange}
                    placeholder={placeholder}
                    suffix={
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconCalendar className="text-secondary" />}
                            onClick={(e) => {
                                e.stopPropagation()
                                setCalendarOpen(true)
                            }}
                        />
                    }
                />
            </Popover>
        </div>
    )
}

export interface DateRangePickerProps {
    dateRange: DateRange
    setDateRange: (dateRange: DateRange) => void
    /** Unique per consumer surface ('logs' | 'tracing'); keys the backing logic. */
    logicKey: string
    /** Preset list shown under "In the last". Defaults to DEFAULT_DATE_RANGE_PICKER_OPTIONS. */
    dateOptions?: DateMappingOption[]
    /** Units offered by the embedded rolling stepper. Defaults to ['minutes', 'hours', 'days']. */
    allowedRollingDateOptions?: DateOption[]
    /** Both required to show the timezone selector; absent => hidden, parsing defaults to UTC. */
    timezone?: string
    onTimezoneChange?: (timezone: string) => void
}

export const DateRangePicker = ({
    dateRange,
    setDateRange,
    logicKey,
    dateOptions = DEFAULT_DATE_RANGE_PICKER_OPTIONS,
    allowedRollingDateOptions = ['minutes', 'hours', 'days'],
    timezone,
    onTimezoneChange,
}: DateRangePickerProps): JSX.Element => {
    const logic = dateRangePickerLogic({ key: logicKey })
    const { popoverOpen, customFrom, customTo, history } = useValues(logic)
    const { setPopoverOpen, setCustomFrom, setCustomTo, addToHistory } = useActions(logic)

    const effectiveTimezone = timezone ?? 'UTC'
    const showTimezone = timezone !== undefined && onTimezoneChange !== undefined

    const handleSelectOption = (option: DateMappingOption): void => {
        setDateRange({ date_from: option.values[0], date_to: option.values[1] ?? null })
        addToHistory({ date_from: option.values[0], date_to: option.values[1] ?? null })
        setPopoverOpen(false)
    }

    const handleSelectHistory = (historyDateRange: DateRange): void => {
        setDateRange(historyDateRange)
        addToHistory(historyDateRange)
        setPopoverOpen(false)
    }

    const handleApplyCustom = (): void => {
        const fromDate = parseDateExpression(customFrom, effectiveTimezone)
        const toDate = customTo ? parseDateExpression(customTo, effectiveTimezone) : null

        if (!fromDate) {
            lemonToast.error('Invalid start date format. Use formats like "-1h", "-30M", or "YYYY-MM-DD HH:mm"')
            return
        }

        if (customTo && !toDate) {
            lemonToast.error('Invalid end date format. Use formats like "-1h", "-30M", or "YYYY-MM-DD HH:mm"')
            return
        }

        if (toDate && fromDate.isAfter(toDate)) {
            lemonToast.error('Start date must be before end date')
            return
        }

        const newDateRange: DateRange = {
            date_from: fromDate.toISOString(),
            date_to: toDate ? toDate.toISOString() : null,
        }

        setDateRange(newDateRange)
        addToHistory(newDateRange)
        setPopoverOpen(false)
    }

    const isOptionSelected = (option: DateMappingOption): boolean => {
        return dateRange.date_from === option.values[0] && (dateRange.date_to ?? null) === (option.values[1] ?? null)
    }

    const currentLabel = formatDateRangeLabel(dateRange, effectiveTimezone, dateOptions)

    return (
        <Popover
            visible={popoverOpen}
            onClickOutside={() => setPopoverOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="w-fit bg-bg-light rounded-lg overflow-hidden flex flex-row-reverse">
                    <div className="flex flex-col gap-1 p-3">
                        <div className="text-xs font-medium text-secondary mb-1">In the last</div>
                        {dateOptions.map((option) => (
                            <LemonButton
                                key={option.key}
                                size="small"
                                type={isOptionSelected(option) ? 'primary' : 'tertiary'}
                                onClick={() => handleSelectOption(option)}
                                fullWidth
                            >
                                {getShortLabel(option)}
                            </LemonButton>
                        ))}
                        <RollingDateRangeFilter
                            dateFrom={dateRange.date_from}
                            selected={true}
                            dateRangeFilterLabel=""
                            onChange={(fromDate) => {
                                setDateRange({ date_from: fromDate, date_to: null })
                                addToHistory({ date_from: fromDate, date_to: null })
                            }}
                            fullWidth
                            allowedDateOptions={allowedRollingDateOptions}
                        />
                    </div>

                    <LemonDivider vertical className="my-3" />

                    <div className="flex flex-col gap-3 p-3 w-fit">
                        <div className="flex flex-col gap-2">
                            <div className="text-xs font-medium text-secondary">Custom range</div>
                            <div className="flex gap-2">
                                <DateTimeInput
                                    value={customFrom}
                                    onChange={setCustomFrom}
                                    placeholder="-1h, -30M..."
                                    timezone={effectiveTimezone}
                                    label="From"
                                />
                                <DateTimeInput
                                    value={customTo}
                                    onChange={setCustomTo}
                                    placeholder="now"
                                    timezone={effectiveTimezone}
                                    label="To"
                                />
                            </div>
                            <LemonButton type="primary" size="small" onClick={handleApplyCustom} fullWidth>
                                Apply
                            </LemonButton>
                        </div>

                        {history.length > 0 && (
                            <>
                                <LemonDivider className="my-0" />
                                <div className="flex flex-col gap-1 flex-1">
                                    <div className="text-xs font-medium text-secondary">Recent</div>
                                    {history.map((historyDateRange, index) => (
                                        <LemonButton
                                            key={index}
                                            size="small"
                                            type="tertiary"
                                            fullWidth
                                            icon={<IconClock className="text-secondary" />}
                                            onClick={() => handleSelectHistory(historyDateRange)}
                                        >
                                            <span className="truncate">
                                                {formatDateRangeLabel(historyDateRange, effectiveTimezone, dateOptions)}
                                            </span>
                                        </LemonButton>
                                    ))}
                                </div>
                            </>
                        )}

                        {showTimezone && (
                            <>
                                <LemonDivider className="my-0" />
                                <TimezoneSelect value={effectiveTimezone} onChange={onTimezoneChange} size="xsmall" />
                            </>
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconCalendar />}
                onClick={() => setPopoverOpen(!popoverOpen)}
            >
                {currentLabel}
            </LemonButton>
        </Popover>
    )
}
