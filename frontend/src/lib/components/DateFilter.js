import React, { Component, useRef, useEffect, useState } from 'react'
import PropTypes from 'prop-types'
import { Select, DatePicker, Button } from 'antd'

import moment from 'moment'

let dateMapping = {
    Today: ['dStart'],
    Yesterday: ['-1d', 'dStart'],
    'Last week': ['-7d'],
    'Last 2 weeks': ['-14d'],
    'Last 30 days': ['-30d'],
    'Last 90 days': ['-90d'],
    'This month': ['mStart'],
    'Previous month': ['-1mStart', '-1mEnd'],
    'Year to date': ['yStart'],
    'All time': ['all'],
}

let isDate = /([0-9]{4}-[0-9]{2}-[0-9]{2})/

function dateFilterToText(date_from, date_to) {
    if (isDate.test(date_from)) return `${date_from} - ${date_to}`
    if (moment.isMoment(date_from)) return `${date_from.format('YYYY-MM-DD')} - ${date_to.format('YYYY-MM-DD')}`
    let name = 'Last 7 days'
    Object.entries(dateMapping).map(([key, value]) => {
        if (value[0] === date_from && value[1] === date_to) name = key
    })[0]
    return name
}

export function DateFilter({ dateFrom, dateTo, onChange, style }) {
    const [rangeDateFrom, setRangeDateFrom] = useState(isDate.test(dateFrom) && moment(dateFrom).toDate())
    const [rangeDateTo, setRangeDateTo] = useState(isDate.test(dateTo) && moment(dateTo).toDate())
    const [dateRangeOpen, setDateRangeOpen] = useState(false)
    const [open, setOpen] = useState(false)

    function onClickOutside() {
        setOpen(false)
        setDateRangeOpen(false)
    }

    function setDate(fromDate, toDate) {
        onChange(fromDate, toDate)
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
        onChange(moment(rangeDateFrom).format('YYYY-MM-DD'), moment(rangeDateTo).format('YYYY-MM-DD'))
    }

    return (
        <Select
            data-attr="date-filter"
            bordered={false}
            id="daterange_selector"
            value={dateFilterToText(dateFrom, dateTo)}
            onChange={_onChange}
            style={{
                marginRight: 4,
                ...style,
            }}
            open={open || dateRangeOpen}
            onBlur={onBlur}
            onClick={onClick}
            listHeight={400}
            dropdownMatchSelectWidth={false}
            dropdownRender={menu => {
                if (dateRangeOpen) {
                    return (
                        <DatePickerDropdown
                            onClick={dropdownOnClick}
                            onDateFromChange={date => setRangeDateFrom(date)}
                            onDateToChange={date => setRangeDateTo(date)}
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

DateFilter.propTypes = {
    onChange: PropTypes.func.isRequired,
}

function DatePickerDropdown(props) {
    const dropdownRef = useRef()
    let [calendarOpen, setCalendarOpen] = useState(false)

    let onClickOutside = event => {
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
                    onOpenChange={open => {
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
                    onOpenChange={open => setCalendarOpen(open)}
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
