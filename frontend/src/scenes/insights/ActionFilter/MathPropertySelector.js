import React from 'react'
import { Tooltip, Select } from 'antd'
import { MATHS } from 'lib/constants'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'

export function MathPropertySelector(props) {
    const applicableProperties = props.properties
        .filter(({ value }) => (value[0] !== '$' || value === '$time') && value !== 'distinct_id' && value !== 'token')
        .sort((a, b) => (a.value + '').localeCompare(b.value))

    return (
        <SelectGradientOverflow
            showSearch
            style={{ width: 150 }}
            onChange={(_, payload) => props.onMathPropertySelect(props.index, payload && payload.value)}
            className="property-select"
            value={props.mathProperty}
            data-attr="math-property-select"
            dropdownMatchSelectWidth={350}
            placeholder={'Select property'}
        >
            {applicableProperties.map(({ value, label }) => (
                <Select.Option
                    key={`math-property-${value}-${props.index}`}
                    value={value}
                    data-attr={`math-property-${value}-${props.index}`}
                >
                    <Tooltip
                        title={
                            <>
                                Calculate {MATHS[props.math].name.toLowerCase()} from property <code>{label}</code>.
                                Note that only {props.name} occurences where <code>{label}</code> is set and a number
                                will be taken into account.
                            </>
                        }
                        placement="right"
                        overlayStyle={{ zIndex: 9999999999 }}
                    >
                        {label}
                    </Tooltip>
                </Select.Option>
            ))}
        </SelectGradientOverflow>
    )
}
