import React from 'react'
import { Dropdown } from './Dropdown'
import { disableMinuteFor, disableHourFor } from '../../scenes/trends/trendsLogic'

let intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

export function IntervalFilter({ filters, setFilters }) {
    const { interval, date_from } = filters
    return (
        <Dropdown
            title={intervalMapping[interval]}
            buttonClassName="btn btn-sm btn-light"
            buttonStyle={{ margin: '0 8px' }}
        >
            <span>
                {Object.entries(intervalMapping).map(([key, value]) => {
                    const minute_disabled = key === 'minute' && disableMinuteFor[date_from]
                    const hour_disabled = key === 'hour' && disableHourFor[date_from]
                    let className = 'dropdown-item'
                    if (minute_disabled || hour_disabled) className = 'dropdown-item disabled'
                    return (
                        <a
                            className={className}
                            key={key}
                            href="#"
                            onClick={e => {
                                e.preventDefault()

                                if (minute_disabled || hour_disabled) {
                                    console.log('minutes disabled')
                                    return false
                                }

                                setFilters({ interval: key })
                            }}
                        >
                            {value}
                        </a>
                    )
                })}
            </span>
        </Dropdown>
    )
}
