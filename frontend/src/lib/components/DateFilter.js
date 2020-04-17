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

export class DateFilter extends Component {
    static propTypes = {
        onChange: PropTypes.func.isRequired,
    }
    constructor(props) {
        super(props)

        this.state = {
            rangeDateFrom: isDate.test(props.dateFrom) && moment(props.dateFrom).toDate(),
            rangeDateTo: isDate.test(props.dateTo) && moment(props.dateTo).toDate(),
            dateRangeOpen: false,
            open: false,
        }
    }

    onClickOutside = () => {
        this.setState({
            open: false,
            dateRangeOpen: false,
        })
    }

    setDate = (from_date, to_date) => {
        this.props.onChange(from_date, to_date)
    }

    dateFilterToText(date_from, date_to) {
        if (isDate.test(date_from)) return `${date_from} - ${date_to}`
        if (moment.isMoment(date_from)) return `${date_from.format('YYYY-MM-DD')} - ${date_to.format('YYYY-MM-DD')}`
        let name = 'Last 7 days'
        Object.entries(dateMapping).map(([key, value]) => {
            if (value[0] == date_from && value[1] == date_to) name = key
        })[0]
        return name
    }

    onChange = v => {
        if (v == 'Date range') {
            if (this.state.open) {
                this.setState({ dateRangeOpen: true, open: false })
            }
        } else this.setDate(dateMapping[v][0], dateMapping[v][1])
    }

    onBlur = () => {
        if (this.state.dateRangeOpen) return
        this.setState({
            open: false,
            dateRangeOpen: false,
        })
    }

    onClick = () => {
        if (this.state.dateRangeOpen) return
        this.setState({
            open: !this.state.open,
        })
    }

    dropdownOnClick = e => {
        e.preventDefault()
        this.setState({ dateRangeOpen: false, open: true })
        document.getElementById('daterange_selector').focus()
    }

    onDateFromChange = date => this.setState({ rangeDateFrom: date })

    onDateToChange = date => this.setState({ rangeDateTo: date })

    onApplyClick = () => {
        this.setState({
            dateRangeOpen: false,
            open: false,
        })
        this.props.onChange(moment(this.state.rangeDateFrom), moment(this.state.rangeDateTo))
    }

    render() {
        let { rangeDateFrom, rangeDateTo } = this.state
        return (
            <Select
                bordered={false}
                id="daterange_selector"
                value={this.dateFilterToText(this.props.dateFrom, this.props.dateTo)}
                onChange={this.onChange}
                style={{
                    marginRight: 4,
                    ...this.props.style,
                }}
                open={this.state.open || this.state.dateRangeOpen}
                onBlur={this.onBlur}
                onClick={this.onClick}
                listHeight={400}
                dropdownMatchSelectWidth={false}
                dropdownRender={menu => {
                    if (this.state.dateRangeOpen) {
                        return (
                            <DatePickerDropdown
                                onClick={this.dropdownOnClick}
                                onDateFromChange={this.onDateFromChange}
                                onDateToChange={this.onDateToChange}
                                onApplyClick={this.onApplyClick}
                                onClickOutside={this.onClickOutside}
                                rangeDateFrom={rangeDateFrom}
                                rangeDateTo={rangeDateTo}
                            ></DatePickerDropdown>
                        )
                    } else if (this.state.open) {
                        return menu
                    }
                }}
            >
                {[
                    ...Object.entries(dateMapping).map(([key, value]) => {
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
