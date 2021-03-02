import React, { useRef, useEffect, useState } from 'react'
import { Select, DatePicker, Button } from 'antd'
import { useValues, useActions } from 'kea'
import moment from 'moment'
import { dateFilterLogic } from './dateFilterLogic'
import { dateMapping, isDate, dateFilterToText } from 'lib/utils'

interface Props {
    defaultValue: string
    showCustom?: boolean
    bordered?: boolean
    makeLabel?: (key: string) => React.ReactNode
    style?: React.CSSProperties
    onChange?: (fromDate: string, toDate: string) => void
    disabled?: boolean
    getPopupContainer?: (props: any) => HTMLElement
    updatePath?: boolean
}

export function DateFilter({
    bordered,
    defaultValue,
    showCustom,
    style,
    disabled,
    makeLabel,
    onChange,
    getPopupContainer,
    updatePath = true,
}: Props): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
    } = useValues(dateFilterLogic)

    const { setDates } = useActions(dateFilterLogic)
    const [rangeDateFrom, setRangeDateFrom] = useState(
        dateFrom && isDate.test(dateFrom as string) ? moment(dateFrom) : undefined
    )
    const [rangeDateTo, setRangeDateTo] = useState(dateTo && isDate.test(dateTo as string) ? moment(dateTo) : undefined)
    const [dateRangeOpen, setDateRangeOpen] = useState(false)
    const [open, setOpen] = useState(false)

    function onClickOutside(): void {
        setOpen(false)
        setDateRangeOpen(false)
    }

    function setDate(fromDate: string, toDate: string): void {
        setDates(fromDate, toDate, updatePath)
        if (onChange) {
            onChange(fromDate, toDate)
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
        setDate(moment(rangeDateFrom).format('YYYY-MM-DD'), moment(rangeDateTo).format('YYYY-MM-DD'))
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
            getPopupContainer={getPopupContainer}
            dropdownRender={(menu: React.ReactElement) => {
                if (dateRangeOpen) {
                    return (
                        <DatePickerDropdown
                            getPopupContainer={getPopupContainer}
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
    onDateFromChange: (date: moment.Moment | undefined) => void
    onDateToChange: (date: moment.Moment | undefined) => void
    onApplyClick: () => void
    rangeDateFrom: string | moment.Moment | undefined
    rangeDateTo: string | moment.Moment | undefined
    getPopupContainer?: (props: any) => HTMLElement
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement | null>(null)
    const [calendarOpen, setCalendarOpen] = useState(false)

    const onClickOutside = (event: MouseEvent): void => {
        const target = (event.composedPath?.()?.[0] || event.target) as HTMLElement

        if (!target) {
            return
        }

        const clickInPickerContainer = dropdownRef.current?.contains(target)
        const clickInDateDropdown = event.composedPath?.()?.find((e) => e?.matches?.('.datefilter-datepicker'))

        if (clickInPickerContainer && calendarOpen && target.tagName !== 'INPUT') {
            setCalendarOpen(false)
            return
        }

        if (!clickInPickerContainer && !clickInDateDropdown) {
            if (calendarOpen) {
                setCalendarOpen(false)
            } else {
                props.onClickOutside()
            }
        }
    }

    useEffect(() => {
        window.addEventListener('mousedown', onClickOutside)
        return () => {
            window.removeEventListener('mousedown', onClickOutside)
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
                    dropdownClassName="datefilter-datepicker"
                    getPopupContainer={props.getPopupContainer}
                    defaultValue={[
                        props.rangeDateFrom
                            ? moment.isMoment(props.rangeDateFrom)
                                ? props.rangeDateFrom
                                : moment(props.rangeDateFrom)
                            : null,
                        props.rangeDateTo
                            ? moment.isMoment(props.rangeDateTo)
                                ? props.rangeDateTo
                                : moment(props.rangeDateTo)
                            : null,
                    ]}
                    open={calendarOpen}
                    onOpenChange={(open) => {
                        if (open) {
                            setCalendarOpen(open)
                        }
                    }}
                    onChange={(dates) => {
                        if (dates && dates.length === 2) {
                            props.onDateFromChange(dates[0] || undefined)
                            props.onDateToChange(dates[1] || undefined)
                            setCalendarOpen(false)
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
