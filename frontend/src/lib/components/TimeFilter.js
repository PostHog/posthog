import React from 'react'
import { Dropdown } from './Dropdown'

let intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    monthly: 'Monthly',
}

export function TimeFilter({ interval, setFilters }) {
    return (
        <Dropdown
            title={intervalMapping[interval]}
            buttonClassName="btn btn-sm btn-light"
            buttonStyle={{ margin: '0 8px' }}
        >
            <span>
                {Object.entries(intervalMapping).map(([key, value]) => (
                    <a
                        className="dropdown-item"
                        key={key}
                        href="#"
                        onClick={e => {
                            e.preventDefault()
                            setFilters({ interval: key })
                        }}
                    >
                        {value}
                    </a>
                ))}
            </span>
        </Dropdown>
    )
}
