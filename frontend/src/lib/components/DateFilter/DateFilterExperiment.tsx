import React, { useRef } from 'react'
import { dateMappingExperiment, dateFilterToText } from 'lib/utils'
import { DateFilterRange } from 'lib/components/DateFilter/DateFilterRangeExperiment'
import { dayjs } from 'lib/dayjs'
import { dateMappingOption } from '~/types'
import './DateFilterExperiment.scss'
import { Tooltip } from 'lib/components/Tooltip'
import { dateFilterLogic } from './DateFilterExperimentLogic'
import { RollingDateRangeFilter } from './RollingDateRangeFilter'
import { useActions, useValues } from 'kea'
import { LemonButtonWithPopup, LemonDivider } from '@posthog/lemon-ui'
import { CalendarOutlined } from '@ant-design/icons'

export interface DateFilterProps {
    defaultValue: string
    showCustom?: boolean
    showRollingRangePicker?: boolean
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    style?: React.CSSProperties
    popupStyle?: React.CSSProperties
    onChange?: (fromDate: string, toDate: string) => void
    disabled?: boolean
    getPopupContainer?: (props: any) => HTMLElement
    dateOptions?: Record<string, dateMappingOption>
    isDateFormatted?: boolean
}

interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
}

export function DateFilterExperiment({
    defaultValue,
    showCustom,
    showRollingRangePicker = true,
    style,
    popupStyle,
    disabled,
    makeLabel,
    onChange,
    getPopupContainer,
    dateFrom,
    dateTo,
    dateOptions = dateMappingExperiment,
    isDateFormatted = true,
}: RawDateFilterProps): JSX.Element {
    const logicProps = { dateFrom, dateTo, onChange, defaultValue, dateOptions, isDateFormatted }
    const { open, openDateRange, close, setRangeDateFrom, setRangeDateTo, setDate } = useActions(
        dateFilterLogic(logicProps)
    )
    const { isOpen, isDateRangeOpen, rangeDateFrom, rangeDateTo, value } = useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)

    function _onChange(v: string | number | null): void {
        if (!v) {
            return
        }
        if (v === 'Date range') {
            openDateRange()
        } else {
            setDate(dateOptions[v].values[0], dateOptions[v].values[1])
            close()
        }
    }

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
        <div ref={optionsRef} className="date-filter-options" onClick={(e) => e.stopPropagation()}>
            {[
                ...Object.entries(dateOptions).map(([key, { values, inactive }]) => {
                    if (key === 'Custom' && !showCustom) {
                        return null
                    }

                    if (inactive && value !== key) {
                        return null
                    }

                    const dateValue = dateFilterToText(values[0], values[1], defaultValue, dateOptions, isDateFormatted)

                    return (
                        <Tooltip key={key} title={makeLabel ? makeLabel(dateValue) : undefined}>
                            <div className="custom-range-button" onClick={() => _onChange(key)}>
                                {key}
                            </div>
                        </Tooltip>
                    )
                }),
            ]}
            {showRollingRangePicker && (
                <RollingDateRangeFilter
                    onChange={(fromDate, toDate) => {
                        setDate(fromDate, toDate)
                        close()
                    }}
                    makeLabel={makeLabel}
                    popupRef={rollingDateRangeRef}
                />
            )}
            <LemonDivider />
            <div className="custom-range-button" onClick={() => _onChange('Date range')}>
                {'Custom fixed time period'}
            </div>
        </div>
    )

    return (
        <LemonButtonWithPopup
            data-attr="date-filter"
            id="daterange_selector"
            onClick={isOpen ? close : open}
            value={value}
            disabled={disabled}
            style={{ ...style, border: '1px solid var(--border)' }} //TODO this is a css hack, so that this button aligns with others on the page who are still on antd
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
                style: popupStyle,
            }}
            icon={<CalendarOutlined />}
        >
            {value}
        </LemonButtonWithPopup>
    )
}
