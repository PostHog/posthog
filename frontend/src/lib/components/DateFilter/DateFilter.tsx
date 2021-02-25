import React, { useRef, useEffect, useState } from 'react'
import { Select, Button } from 'antd'
import { useValues, useActions } from 'kea'
import * as dayjs from 'dayjs'
import { dateFilterLogic } from './dateFilterLogic'
import { dateMapping, isDate, dateFilterToText } from 'lib/utils'

import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/es/date-picker/generatePicker'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

interface Props {
    defaultValue: string
    showCustom?: boolean
    bordered?: boolean
    makeLabel?: (key: string) => React.ReactNode
    style?: React.CSSProperties
    onChange?: () => void
    disabled?: boolean
}

export function DateFilter({
    bordered,
    defaultValue,
    showCustom,
    style,
    disabled,
    makeLabel,
    onChange,
}: Props): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
    } = useValues(dateFilterLogic)

    const { setDates } = useActions(dateFilterLogic)
    const [rangeDateFrom, setRangeDateFrom] = useState(
        dateFrom && isDate.test(dateFrom as string) ? dayjs(dateFrom) : undefined
    )
    const [rangeDateTo, setRangeDateTo] = useState(dateTo && isDate.test(dateTo as string) ? dayjs(dateTo) : undefined)
    const [dateRangeOpen, setDateRangeOpen] = useState(false)
    const [open, setOpen] = useState(false)

    function onClickOutside(): void {
        setOpen(false)
        setDateRangeOpen(false)
    }

    function setDate(fromDate: string, toDate: string): void {
        setDates(fromDate, toDate)
        if (onChange) {
            onChange()
        }
    }

    function _onChange(v: string): void {
        if (v === 'Date range') {
            if (open) {
                setOpen(false)
                setDateRangeOpen(true)
            }
        } else {
            setDate(dateMapping[v][0], dateMapping[v][1])
        }
    }

    function onBlur(): void {
        if (dateRangeOpen) {
            return
        }
        onClickOutside()
    }

    function onClick(): void {
        if (dateRangeOpen) {
            return
        }
        setOpen(!open)
    }

    function dropdownOnClick(e: React.MouseEvent): void {
        e.preventDefault()
        setOpen(true)
        setDateRangeOpen(false)
        document.getElementById('daterange_selector')?.focus()
    }

    function onApplyClick(): void {
        onClickOutside()
        setDate(dayjs(rangeDateFrom).format('YYYY-MM-DD'), dayjs(rangeDateTo).format('YYYY-MM-DD'))
    }

    return (
        <Select
            data-attr="date-filter"
            bordered={bordered}
            id="daterange_selector"
            value={dateFilterToText(dateFrom, dateTo, defaultValue)}
            onChange={_onChange}
            style={{
                marginRight: 4,
                ...style,
            }}
            open={open || dateRangeOpen}
            onBlur={onBlur}
            onClick={onClick}
            listHeight={440}
            dropdownMatchSelectWidth={false}
            disabled={disabled}
            optionLabelProp={makeLabel ? 'label' : undefined}
            dropdownRender={(menu: React.ReactElement) => {
                if (dateRangeOpen) {
                    return (
                        <DatePickerDropdown
                            onClick={dropdownOnClick}
                            onDateFromChange={(date) => setRangeDateFrom(date)}
                            onDateToChange={(date) => setRangeDateTo(date)}
                            onApplyClick={onApplyClick}
                            onClickOutside={onClickOutside}
                            rangeDateFrom={rangeDateFrom}
                            rangeDateTo={rangeDateTo}
                        />
                    )
                } else {
                    return menu
                }
            }}
        >
            {[
                ...Object.entries(dateMapping).map(([key]) => {
                    if (key === 'Custom' && !showCustom) {
                        return null
                    }
                    return (
                        <Select.Option key={key} value={key} label={makeLabel ? makeLabel(key) : undefined}>
                            {key}
                        </Select.Option>
                    )
                }),

                <Select.Option key={'Date range'} value={'Date range'}>
                    {'Date range'}
                </Select.Option>,
            ]}
        </Select>
    )
}

function DatePickerDropdown(props: {
    onClickOutside: () => void
    onClick: (e: React.MouseEvent) => void
    onDateFromChange: (date: dayjs.Dayjs | undefined) => void
    onDateToChange: (date: dayjs.Dayjs | undefined) => void
    onApplyClick: () => void
    rangeDateFrom: string | dayjs.Dayjs | undefined
    rangeDateTo: string | dayjs.Dayjs | undefined
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement | null>(null)
    const [calendarOpen, setCalendarOpen] = useState(false)

    const onClickOutside = (event: MouseEvent): void => {
        if ((!event.target || !dropdownRef.current?.contains(event.target as any)) && !calendarOpen) {
            props.onClickOutside()
        }
    }

    useEffect(() => {
        document.addEventListener('mousedown', onClickOutside)
        return () => {
            document.removeEventListener('mousedown', onClickOutside)
        }
    }, [calendarOpen])

    return (
        <div ref={dropdownRef}>
            <a
                style={{
                    margin: '0 1rem',
                    color: 'rgba(0, 0, 0, 0.2)',
                    fontWeight: 700,
                }}
                href="#"
                onClick={props.onClick}
            >
                &lt;
            </a>
            <hr style={{ margin: '0.5rem 0' }} />
            <div style={{ padding: '0 1rem' }}>
                <label className="secondary">From date</label>
                <br />
                <DatePicker.RangePicker
                    defaultValue={[
                        props.rangeDateFrom
                            ? dayjs.isDayjs(props.rangeDateFrom)
                                ? props.rangeDateFrom
                                : dayjs(props.rangeDateFrom)
                            : null,
                        props.rangeDateTo
                            ? dayjs.isDayjs(props.rangeDateTo)
                                ? props.rangeDateTo
                                : dayjs(props.rangeDateTo)
                            : null,
                    ]}
                    onOpenChange={(open) => {
                        setCalendarOpen(open)
                    }}
                    onChange={(dates) => {
                        if (dates && dates.length === 2) {
                            props.onDateFromChange(dates[0] || undefined)
                            props.onDateToChange(dates[1] || undefined)
                        }
                    }}
                    popupStyle={{ zIndex: 999999 }}
                />
                <br />
                <Button
                    type="default"
                    disabled={!props.rangeDateTo || !props.rangeDateFrom}
                    style={{ marginTop: '1rem', marginBottom: '1rem' }}
                    onClick={props.onApplyClick}
                >
                    Apply filter
                </Button>
            </div>
        </div>
    )
}
