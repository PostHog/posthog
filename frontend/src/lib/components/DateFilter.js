import React, { Component } from 'react'
import PropTypes from 'prop-types'
import { Dropdown } from './Dropdown'
import DatePicker from 'react-datepicker'
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
            rangeDateFrom:
                isDate.test(props.dateFrom) && moment(props.dateFrom).toDate(),
            rangeDateTo:
                isDate.test(props.dateTo) && moment(props.dateTo).toDate(),
        }
        if (this.state.rangeDateFrom || this.state.rangeDateTo)
            this.state.dateRangeOpen = true
        this.setDate = this.setDate.bind(this)
    }
    setDate(e, from_date, to_date) {
        e.preventDefault()
        this.props.onChange(from_date, to_date)
    }
    dateFilterToText(date_from, date_to) {
        if (isDate.test(date_from)) return `${date_from} - ${date_to}`
        if (moment.isMoment(date_from)) return `${date_from.format("YYYY-MM-DD")} - ${date_to.format("YYYY-MM-DD")}`
        let name = 'Last 7 days'
        Object.entries(dateMapping).map(([key, value]) => {
            if (value[0] == date_from && value[1] == date_to) name = key
        })[0]
        return name
    }
    render() {
        let { dateRangeOpen, rangeDateFrom, rangeDateTo } = this.state
        return (
            <Dropdown
                title={this.dateFilterToText(
                    this.props.dateFrom,
                    this.props.dateTo
                )}
                buttonClassName="btn btn-sm btn-light"
                buttonStyle={{ margin: '0 8px' }}
            >
                {!dateRangeOpen ? (
                    <span>
                        {Object.entries(dateMapping).map(([key, value]) => (
                            <a
                                className="dropdown-item"
                                key={key}
                                href="#"
                                onClick={e =>
                                    this.setDate(e, value[0], value[1])
                                }
                            >
                                {key}
                            </a>
                        ))}
                        <a
                            className="dropdown-item dropdown-no-close"
                            href="#"
                            onClick={e => {
                                e.preventDefault()
                                this.setState({ dateRangeOpen: true })
                            }}
                        >
                            Date range
                        </a>
                    </span>
                ) : (
                    <div className="dropdown-no-close">
                        <a
                            style={{
                                margin: '0 1rem',
                                color: 'rgba(0, 0, 0, 0.2)',
                                fontWeight: 700,
                            }}
                            href="#"
                            onClick={e => {
                                e.preventDefault()
                                this.setState({ dateRangeOpen: false })
                            }}
                        >
                            &lt;
                        </a>
                        <hr style={{ margin: '0.5rem 0' }} />
                        <div style={{ padding: '0 1rem' }}>
                            <label className="secondary">From date</label>
                            <DatePicker
                                className="form-control"
                                selected={rangeDateFrom}
                                maxDate={new Date()}
                                onChange={date =>
                                    this.setState({ rangeDateFrom: date })
                                }
                            />
                            <br />
                            <label className="secondary">To date</label>
                            <DatePicker
                                className="form-control"
                                selected={rangeDateTo}
                                maxDate={new Date()}
                                onChange={date =>
                                    this.setState({ rangeDateTo: date })
                                }
                            />
                            <button
                                style={{ marginTop: '1rem' }}
                                className="btn btn-sm btn-outline-success"
                                onClick={e =>
                                    this.props.onChange(
                                        moment(rangeDateFrom),
                                        moment(rangeDateTo)
                                    )
                                }
                            >
                                Apply filter
                            </button>
                        </div>
                    </div>
                )}
            </Dropdown>
        )
    }
}
