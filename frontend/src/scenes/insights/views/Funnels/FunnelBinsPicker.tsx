import { IconGraph } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'
import { Select } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BIN_COUNT_AUTO } from 'lib/constants'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { BinCountValue } from '~/types'

// Constraints as defined in funnel_time_to_convert.py:34
const MIN = 1
const MAX = 90
const NUMBER_PRESETS = new Set([5, 15, 25, 50, 90])

interface BinOption {
    key?: string
    label: string
    value: BinCountValue | 'custom'
    display: boolean
}

const options: BinOption[] = [
    {
        label: 'Auto bins',
        value: BIN_COUNT_AUTO,
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

type FunnelBinsPickerProps = { disabled?: boolean }

export function FunnelBinsPicker({ disabled }: FunnelBinsPickerProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, numericBinCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const setBinCount = (binCount: BinCountValue): void => {
        updateInsightFilter({ binCount: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
    }

    return (
        <Select
            id="funnel-bin-filter"
            dropdownClassName="funnel-bin-filter-dropdown"
            data-attr="funnel-bin-filter"
            defaultValue={BIN_COUNT_AUTO}
            value={funnelsFilter?.binCount || BIN_COUNT_AUTO}
            onSelect={(count) => setBinCount(count)}
            dropdownRender={(menu) => {
                return (
                    <>
                        {menu}
                        <div>
                            <LemonInput
                                type="number"
                                className="funnel-bins-custom-picker"
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
            disabled={disabled}
        >
            <Select.OptGroup label="Bin Count">
                {options.map((option) => {
                    if (option.value === 'custom') {
                        return null
                    }
                    return (
                        <Select.Option
                            className={clsx({ hidden: !option.display })}
                            key={option.value}
                            value={option.value}
                            label={
                                <>
                                    <IconGraph /> {option.label}
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
