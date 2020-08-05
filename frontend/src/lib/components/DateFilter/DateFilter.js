import React, { useRef, useEffect, useState } from 'react'
import { Select, DatePicker, Button } from 'antd'
import { useValues, useActions } from 'kea'
import moment from 'moment'
import { dateFilterLogic } from './dateFilterLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { dateMapping, isDate, dateFilterToText } from 'lib/utils'

export function DateFilter({ style, filters, view }) {
    const {
        dates: { dateFrom, dateTo },
    } = useValues(dateFilterLogic)
    const { setDates } = useActions(dateFilterLogic)
    const [rangeDateFrom, setRangeDateFrom] = useState(isDate.test(dateFrom) && moment(dateFrom).toDate())
    const [rangeDateTo, setRangeDateTo] = useState(isDate.test(dateTo) && moment(dateTo).toDate())
    const [dateRangeOpen, setDateRangeOpen] = useState(false)
    const [open, setOpen] = useState(false)

    function onClickOutside() {
        setOpen(false)
        setDateRangeOpen(false)
    }

    function setDate(fromDate, toDate) {
        setDates(fromDate, toDate)
    }

    function _onChange(v) {
        if (v === 'Date range') {
            if (open) {
                setOpen(false)
                setDateRangeOpen(true)
            }
        } else setDate(dateMapping[v][0], dateMapping[v][1])
    }

    function onBlur() {
        if (dateRangeOpen) return
        onClickOutside()
    }

    function onClick() {
        if (dateRangeOpen) return
        setOpen(!open)
    }

    function dropdownOnClick(e) {
        e.preventDefault()
        setOpen(true)
        setDateRangeOpen(false)
        document.getElementById('daterange_selector').focus()
    }

    function onApplyClick() {
        onClickOutside()
        setDate(moment(rangeDateFrom).format('YYYY-MM-DD'), moment(rangeDateTo).format('YYYY-MM-DD'))
    }

    return (
        <Select
            data-attr="date-filter"
            bordered={false}
            id="daterange_selector"
            value={dateFilterToText(
                view === ViewType.FUNNELS ? filters.date_from : dateFrom,
                view === ViewType.FUNNELS ? filters.date_to : dateTo
            )}
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
            dropdownRender={(menu) => {
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
                } else if (open) {
                    return menu
                }
            }}
        >
            {[
                ...Object.entries(dateMapping).map(([key]) => {
                    return (
                        <Select.Option key={key} value={key}>
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

function DatePickerDropdown(props) {
    const dropdownRef = useRef()
    let [calendarOpen, setCalendarOpen] = useState(false)

    let onClickOutside = (event) => {
        if (!dropdownRef.current.contains(event.target) && !calendarOpen) {
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
        <div className="dropdown" ref={dropdownRef}>
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
                <DatePicker
                    popupStyle={{ zIndex: 999999 }}
                    onOpenChange={(open) => {
                        setCalendarOpen(open)
                    }}
                    defaultValue={
                        props.rangeDateFrom
                            ? moment.isMoment(props.rangeDateFrom)
                                ? props.rangeDateFrom
                                : moment(props.rangeDateFrom)
                            : null
                    }
                    onChange={props.onDateFromChange}
                />
                <br />
                <br />
                <label className="secondary">To date</label>
                <br />
                <DatePicker
                    popupStyle={{ zIndex: 999999 }}
                    onOpenChange={(open) => setCalendarOpen(open)}
                    defaultValue={
                        props.rangeDateTo
                            ? moment.isMoment(props.rangeDateTo)
                                ? props.rangeDateTo
                                : moment(props.rangeDateTo)
                            : null
                    }
                    onChange={props.onDateToChange}
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
