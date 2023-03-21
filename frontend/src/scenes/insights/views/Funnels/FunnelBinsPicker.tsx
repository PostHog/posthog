import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { BIN_COUNT_AUTO } from 'lib/constants'
import { InputNumber, Select } from 'antd'
import { BinCountValue } from '~/types'
import { BarChartOutlined } from '@ant-design/icons'
import clsx from 'clsx'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelsFilter } from '~/queries/schema'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

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

export function FunnelBinsPickerDataExploration(props: FunnelBinsPickerProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, numericBinCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const setBinCount = (binCount: BinCountValue): void => {
        updateInsightFilter({ bin_count: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
    }

    return (
        <FunnelBinsPickerComponent
            funnelsFilter={funnelsFilter}
            setBinCount={setBinCount}
            numericBinCount={numericBinCount}
            {...props}
        />
    )
}

export function FunnelBinsPicker(props: FunnelBinsPickerProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters, numericBinCount } = useValues(funnelLogic(insightProps))
    const { setBinCount } = useActions(funnelLogic(insightProps))

    return (
        <FunnelBinsPickerComponent
            funnelsFilter={filters}
            setBinCount={setBinCount}
            numericBinCount={numericBinCount}
            {...props}
        />
    )
}

type FunnelBinsPickerComponentProps = FunnelBinsPickerProps & {
    funnelsFilter?: FunnelsFilter | null
    setBinCount: (binCount: BinCountValue) => void
    numericBinCount: number
}

function FunnelBinsPickerComponent({
    funnelsFilter,
    setBinCount,
    numericBinCount,
    disabled,
}: FunnelBinsPickerComponentProps): JSX.Element {
    return (
        <Select
            id="funnel-bin-filter"
            dropdownClassName="funnel-bin-filter-dropdown"
            data-attr="funnel-bin-filter"
            defaultValue={BIN_COUNT_AUTO}
            value={funnelsFilter?.bin_count || BIN_COUNT_AUTO}
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
