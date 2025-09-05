import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

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
    value: BinCountValue
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
]

export function FunnelBinsPicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { funnelsFilter, numericBinCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const [visible, setVisible] = useState<boolean>(false)

    const setBinCount = (binCount: BinCountValue): void => {
        updateInsightFilter({ binCount: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
    }

    const preferredOptions = BIN_OPTIONS.filter((o) => o.display).map((bin) => {
        return {
            value: bin.value as BinCountValue,
            label: bin.label,
            icon: <IconGraph />,
        }
    })

    const selectedValue = funnelsFilter?.binCount || BIN_COUNT_AUTO
    const selectedOption = BIN_OPTIONS.find((o) => o.value === selectedValue)

    const overlay = (
        <div className="deprecated-space-y-px" onClick={(e) => e.stopPropagation()}>
            {preferredOptions.map((bin) => (
                <LemonButton
                    fullWidth
                    key={bin.value}
                    active={bin.value === selectedValue}
                    onClick={() => {
                        setVisible(false)
                        setBinCount(bin.value)
                    }}
                >
                    {bin.label}
                </LemonButton>
            ))}
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
        </div>
    )

    return (
        <>
            <LemonDropdown
                data-attr="funnel-bin-filter"
                matchWidth
                visible={visible}
                closeOnClickInside={false}
                onClickOutside={() => setVisible(false)}
                overlay={overlay}
                className="w-32"
                placement="bottom-end"
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconGraph />}
                    onClick={() => setVisible(true)}
                    disabledReason={editingDisabledReason}
                >
                    {selectedOption?.label}
                </LemonButton>
            </LemonDropdown>
        </>
    )
}
