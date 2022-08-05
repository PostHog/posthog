import React, { useRef } from 'react'
import { dateMapping, dateFilterToText, uuid } from 'lib/utils'
import { DateFilterRange } from 'lib/components/DateFilter/DateFilterRange'
import { dateMappingOption } from '~/types'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/components/Tooltip'
import { dateFilterLogic } from './dateFilterLogic'
import { RollingDateRangeFilter } from './RollingDateRangeFilter'
import { useActions, useValues } from 'kea'
import { LemonButtonWithPopup, LemonDivider, LemonButton } from '@posthog/lemon-ui'
import { CalendarOutlined } from '@ant-design/icons'

export interface DateFilterProps {
    defaultValue: string
    showCustom?: boolean
    showRollingRangePicker?: boolean
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    className?: string
    style?: React.CSSProperties
    onChange?: (fromDate: string, toDate: string) => void
    disabled?: boolean
    getPopupContainer?: () => HTMLElement
    dateOptions?: dateMappingOption[]
    isDateFormatted?: boolean
}
interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
}

export function DateFilter({
    defaultValue,
    showCustom,
    showRollingRangePicker = true,
    style,
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
    const logicProps = { key, dateFrom, dateTo, onChange, defaultValue, dateOptions, isDateFormatted }
    const { open, openDateRange, close, setRangeDateFrom, setRangeDateTo, setDate } = useActions(
        dateFilterLogic(logicProps)
    )
    const { isOpen, isDateRangeOpen, rangeDateFrom, rangeDateTo, value, isFixedDateRange, isRollingDateRange } =
        useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)

    function dropdownOnClick(e: React.MouseEvent): void {
        e.preventDefault()
        open()
        document.getElementById('daterange_selector')?.focus()
    }

    function onApplyClick(): void {
        close()
        const formattedRangeDateFrom = dayjs(rangeDateFrom).format('YYYY-MM-DD')
        const formattedRangeDateTo = dayjs(rangeDateTo).format('YYYY-MM-DD')
        setDate(formattedRangeDateFrom, formattedRangeDateTo)
    }

    const popupOverlay = isDateRangeOpen ? (
        <DateFilterRange
            getPopupContainer={getPopupContainer}
            onClick={dropdownOnClick}
            onDateFromChange={(date) => setRangeDateFrom(date)}
            onDateToChange={(date) => setRangeDateTo(date)}
            onApplyClick={onApplyClick}
            onClickOutside={close}
            rangeDateFrom={rangeDateFrom}
            rangeDateTo={rangeDateTo}
            disableBeforeYear={2015}
        />
    ) : (
        <div ref={optionsRef} onClick={(e) => e.stopPropagation()}>
            {dateOptions.map(({ key, values, inactive }) => {
                if (key === 'Custom' && !showCustom) {
                    return null
                }

                if (inactive && value !== key) {
                    return null
                }

                const isHighlighted = dateFrom === values[0] && dateTo === values[1]
                const dateValue = dateFilterToText(values[0], values[1], defaultValue, dateOptions, isDateFormatted)

                return (
                    <Tooltip key={key} title={makeLabel ? makeLabel(dateValue) : undefined}>
                        <LemonButton
                            key={key}
                            onClick={() => {
                                setDate(values[0], values[1])
                                close()
                            }}
                            type={isHighlighted ? 'highlighted' : 'stealth'}
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
                        close()
                    }}
                    makeLabel={makeLabel}
                    popup={{
                        ref: rollingDateRangeRef,
                    }}
                />
            )}
            <LemonDivider />
            <LemonButton onClick={openDateRange} type={isFixedDateRange ? 'highlighted' : 'stealth'} fullWidth>
                {'Custom fixed time period'}
            </LemonButton>
        </div>
    )

    return (
        <LemonButtonWithPopup
            data-attr="date-filter"
            id="daterange_selector"
            onClick={isOpen ? close : open}
            value={value}
            disabled={disabled}
            className={className}
            style={style}
            bordered={true}
            size={'small'}
            type={'stealth'}
            popup={{
                onClickOutside: close,
                visible: isOpen || isDateRangeOpen,
                overlay: popupOverlay,
                placement: 'bottom-start',
                actionable: true,
                closeOnClickInside: false,
                additionalRefs: [rollingDateRangeRef, '.datefilter-datepicker'],
                getPopupContainer,
            }}
            icon={<CalendarOutlined />}
        >
            {value}
        </LemonButtonWithPopup>
    )
}
