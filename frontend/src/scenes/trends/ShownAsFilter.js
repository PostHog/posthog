import React, { Component } from 'react'
import Select from 'react-select'
import { selectStyle } from '../../lib/utils'
export function ShownAsFilter({ shown_as, onChange }) {
    let options = ['Volume', 'Stickiness']
    return (
        <div>
            <div style={{ width: 200 }}>
                <Select
                    options={[
                        { label: 'Volume', value: 'Volume' },
                        { label: 'Stickiness', value: 'Stickiness' },
                    ]}
                    styles={selectStyle}
                    value={{ label: shown_as || 'Volume', value: shown_as }}
                    onChange={item => onChange(item.value)}
                />
            </div>
            {shown_as == 'Stickiness' && <small><i>Stickiness shows you how many days users performed an action within the timeframe. If a user did an action on Monday and came back and did it twice on Friday, it would be listed as "2 days" in the chart.</i></small>}
        </div>
    )
}
