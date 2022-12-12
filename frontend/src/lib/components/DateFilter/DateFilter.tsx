import { useRef } from 'react'
import { dateMapping, dateFilterToText, uuid } from 'lib/utils'
import { DateMappingOption } from '~/types'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/components/Tooltip'
import { dateFilterLogic } from './dateFilterLogic'
import { RollingDateRangeFilter } from './RollingDateRangeFilter'
import { useActions, useValues } from 'kea'
import { LemonButtonWithPopup, LemonDivider, LemonButton } from '@posthog/lemon-ui'
import { IconCalendar } from '../icons'
import { LemonCalendarSelect } from 'lib/components/LemonCalendar/LemonCalendarSelect'
import { LemonCalendarRange } from 'lib/components/LemonCalendarRange/LemonCalendarRange'
import { DateFilterLogicProps, DateFilterView } from 'lib/components/DateFilter/types'

export interface DateFilterProps {
    showCustom?: boolean
    showRollingRangePicker?: boolean
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    className?: string
    onChange?: (fromDate: string | null, toDate: string | null) => void
    disabled?: boolean
    getPopupContainer?: () => HTMLElement
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
}
interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
}

export function DateFilter({
    showCustom,
    showRollingRangePicker = true,
    className,
    disabled,
    makeLabel,
    onChange,
    getPopupContainer,
    dateFrom,
    dateTo,
    dateOptions = dateMapping,
    isDateFormatted = true,
}: RawDateFilterProps): JSX.Element {
    const key = useRef(uuid()).current
    const logicProps: DateFilterLogicProps = {
        key,
        dateFrom,
        dateTo,
        onChange,
        dateOptions,
        isDateFormatted,
    }
    const { open, openFixedRange, openDateToNow, close, setRangeDateFrom, setRangeDateTo, setDate, applyRange } =
        useActions(dateFilterLogic(logicProps))
    const { isVisible, view, rangeDateFrom, rangeDateTo, label, isFixedRange, isDateToNow, isRollingDateRange } =
        useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)

    const popupOverlay =
        view === DateFilterView.FixedRange ? (
            <LemonCalendarRange
                value={[(rangeDateTo ?? dayjs()).format('YYYY-MM-DD'), (rangeDateTo ?? dayjs()).format('YYYY-MM-DD')]}
                onChange={([from, to]) => {
                    setRangeDateFrom(from ? dayjs(from) : null)
                    setRangeDateTo(to ? dayjs(to) : null)
                    applyRange()
                }}
                onClose={open}
                months={2}
            />
        ) : view === DateFilterView.DateToNow ? (
            <LemonCalendarSelect
                value={(rangeDateFrom as any) ?? dayjs().format('YYYY-MM-DD')}
                onChange={(date) => {
                    setRangeDateFrom(dayjs(date))
                    setRangeDateTo(null)
                    applyRange()
                }}
                onClose={open}
            />
        ) : (
            <div ref={optionsRef} onClick={(e) => e.stopPropagation()}>
                {dateOptions.map(({ key, values, inactive }) => {
                    if (key === 'Custom' && !showCustom) {
                        return null
                    }

                    if (inactive && label !== key) {
                        return null
                    }

                    const isActive =
                        (dateFrom ?? null) === (values[0] ?? null) && (dateTo ?? null) === (values[1] ?? null)
                    const dateValue = dateFilterToText(
                        values[0],
                        values[1],
                        'No date selected',
                        dateOptions,
                        isDateFormatted
                    )

                    return (
                        <Tooltip key={key} title={makeLabel ? makeLabel(dateValue) : undefined}>
                            <LemonButton
                                key={key}
                                onClick={() => setDate(values[0] || null, values[1] || null)}
                                active={isActive}
                                status="stealth"
                                fullWidth
                            >
                                {key}
                            </LemonButton>
                        </Tooltip>
                    )
                })}
                {showRollingRangePicker && (
                    <RollingDateRangeFilter
                        dateFrom={dateFrom}
                        selected={isRollingDateRange}
                        onChange={(fromDate) => {
                            setDate(fromDate, '')
                        }}
                        makeLabel={makeLabel}
                        popup={{
                            ref: rollingDateRangeRef,
                        }}
                    />
                )}
                <LemonDivider />
                <LemonButton onClick={openDateToNow} active={isDateToNow} status="stealth" fullWidth>
                    From custom date until now…
                </LemonButton>
                <LemonButton onClick={openFixedRange} active={isFixedRange} status="stealth" fullWidth>
                    Custom fixed date range…
                </LemonButton>
            </div>
        )

    return (
        <LemonButtonWithPopup
            data-attr="date-filter"
            id="daterange_selector"
            onClick={isVisible ? close : open}
            disabled={disabled}
            className={className}
            size={'small'}
            type={'secondary'}
            status="stealth"
            popup={{
                onClickOutside: close,
                visible: isVisible,
                overlay: popupOverlay,
                placement: 'bottom-start',
                actionable: true,
                closeOnClickInside: false,
                additionalRefs: [rollingDateRangeRef, '.datefilter-datepicker'],
                getPopupContainer,
            }}
            icon={<IconCalendar />}
        >
            {label}
        </LemonButtonWithPopup>
    )
}
