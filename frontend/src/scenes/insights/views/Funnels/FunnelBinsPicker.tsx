import { IconGraph } from '@posthog/icons'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BIN_COUNT_AUTO } from 'lib/constants'
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

const BIN_OPTIONS: BinOption[] = [
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

export function FunnelBinsPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, numericBinCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const setBinCount = (binCount: BinCountValue): void => {
        updateInsightFilter({ binCount: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
    }

    const preferredBins = BIN_OPTIONS.filter((o) => o.display)
    const preferredBinCounts = preferredBins.map((b) => b.value)

    const options = [
        {
            title: 'Bin Count',
            options: preferredBins.map((bin) => {
                return {
                    value: bin.value as BinCountValue,
                    label: bin.label,
                    icon: <IconGraph />,
                }
            }),
        },
    ]

    console.log(preferredBinCounts)
    console.log(numericBinCount)

    return (
        <>
            <LemonSelect
                data-attr="funnel-bin-filter"
                value={funnelsFilter?.binCount || BIN_COUNT_AUTO}
                onChange={(count) => setBinCount(count === 'custom' ? 0 : count)}
                dropdownMatchSelectWidth
                options={options}
                menu={{ closeParentPopoverOnClickInside: false }}
            />
            {!preferredBinCounts.includes(numericBinCount) && (
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
                    suffix={<>bins</>}
                />
            )}
        </>
    )
}
