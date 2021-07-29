import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { BinCountPresets } from 'lib/constants'
import { InputNumber, Select } from 'antd'
import { BinCountValues } from '~/types'
import { BarChartOutlined } from '@ant-design/icons'

// export const binOptionsMapping: Record<string, number | 'auto' | 'custom'> = {
//     custom: 'custom',
//     auto: 'auto',
//     ...Object.assign({}, ...Array.from([3, 5, 10, 25, 50, 75, 90], (v) => ({ [v]: v }))),
// }

const options = [
    {
        label: 'Automatic',
        value: BinCountPresets.auto,
    },
    ...Array.from([5, 10, 15, 25, 50, 90], (v) => ({ label: `${v} bins`, value: v })),
    {
        label: 'Custom',
        value: BinCountPresets.custom,
    },
]

export function FunnelBinsPicker(): JSX.Element {
    const { binCount } = useValues(funnelLogic)
    const { setBinCount } = useActions(funnelLogic)
    const [open, setOpen] = useState(false)
    const [customPickerOpen, setCustomPickerOpen] = useState(false)

    function onClickOutside(): void {
        setOpen(false)
        setCustomPickerOpen(false)
    }

    return (
        <Select
            defaultValue={BinCountPresets.auto}
            value={binCount}
            onChange={(count: BinCountValues) => {
                if (count === BinCountPresets.custom) {
                    if (open) {
                        setOpen(false)
                        setCustomPickerOpen(true)
                    }
                } else {
                    setBinCount(count)
                }
            }}
            onBlur={() => {
                if (!customPickerOpen) {
                    onClickOutside()
                }
            }}
            onClick={() => {
                if (!customPickerOpen) {
                    setOpen(!open)
                }
            }}
            listHeight={440}
            open={open || customPickerOpen}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-time-conversion-bin-selector"
            optionLabelProp="label"
            dropdownRender={(menu: React.ReactElement) => {
                if (customPickerOpen) {
                    return (
                        <div>
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
                            <InputNumber />
                        </div>
                    )
                }
                return menu
            }}
        >
            <Select.OptGroup label="Bin Count">
                {options.map((option) => {
                    // if (option.value === BinCountPresets.custom) {
                    //     return null
                    // }
                    return (
                        <Select.Option
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
