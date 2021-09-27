import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { BinCountAuto } from 'lib/constants'
import { InputNumber, Select } from 'antd'
import { BinCountValue } from '~/types'
import { BarChartOutlined } from '@ant-design/icons'
import clsx from 'clsx'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'

interface BinOption {
    key?: string
    label: string
    value: BinCountValue | 'custom'
    display: boolean
}

const MIN = 0,
    MAX = 90 // constraints defined by backend #4995
const NUMBER_PRESETS = new Set([5, 15, 25, 50, 90])
const options: BinOption[] = [
    {
        label: 'Auto bins',
        value: BinCountAuto,
        display: true,
    },
    ...Array.from(Array.from(Array(MAX + 1).keys()), (v) => ({
        label: `${v} bins`,
        value: v,
        display: NUMBER_PRESETS.has(v),
    })),
    {
        label: 'Custom',
        value: 'custom',
        display: true,
    },
]

export function FunnelBinsPicker(): JSX.Element {
    const { filters, numericBinCount } = useValues(funnelLogic)
    const { setBinCount } = useActions(funnelLogic)

    return (
        <Select
            id="funnel-bin-filter"
            dropdownClassName="funnel-bin-filter-dropdown"
            data-attr="funnel-bin-filter"
            defaultValue={BinCountAuto}
            value={filters.bin_count || BinCountAuto}
            onSelect={(count) => setBinCount(count)}
            dropdownRender={(menu) => {
                return (
                    <>
                        {menu}
                        <div>
                            <InputNumber
                                className="funnel-bins-custom-picker"
                                size="middle"
                                min={MIN}
                                max={MAX}
                                value={numericBinCount}
                                onChange={(count) => {
                                    const parsedCount = typeof count === 'string' ? parseInt(count) : count
                                    if (parsedCount) {
                                        setBinCount(parsedCount)
                                    }
                                }}
                            />{' '}
                            bins
                        </div>
                    </>
                )
            }}
            listHeight={440}
            bordered={false}
            dropdownMatchSelectWidth={false}
            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
            optionLabelProp="label"
        >
            <Select.OptGroup label="Bin Count">
                {options.map((option) => {
                    if (option.value === 'custom') {
                        return null
                    }
                    return (
                        <Select.Option
                            className={clsx({ 'select-option-hidden': !option.display })}
                            key={option.value}
                            value={option.value}
                            label={
                                <>
                                    <BarChartOutlined /> {option.label}
                                </>
                            }
                        >
                            {option.label}
                        </Select.Option>
                    )
                })}
            </Select.OptGroup>
        </Select>
    )
}
