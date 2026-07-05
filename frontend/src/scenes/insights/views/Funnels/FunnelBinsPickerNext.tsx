import { useActions, useValues } from 'kea'
import { type ChangeEvent, useState } from 'react'

import { IconGraph } from '@posthog/icons'
import { Button, Input, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { BIN_COUNT_AUTO } from 'lib/constants'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { BinCountValue } from '~/types'

// Constraints as defined in funnel_time_to_convert.py:34
const MIN = 1
const MAX = 90
const NUMBER_PRESETS = [5, 15, 25, 50, 90]

export function FunnelBinsPickerNext(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { funnelsFilter, numericBinCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const [open, setOpen] = useState(false)

    const setBinCount = (binCount: BinCountValue): void => {
        updateInsightFilter({ binCount: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
    }

    const selectedValue = funnelsFilter?.binCount || BIN_COUNT_AUTO
    const label = selectedValue === BIN_COUNT_AUTO ? 'Auto bins' : `${selectedValue} bins`

    const presets: { value: BinCountValue; label: string }[] = [
        { value: BIN_COUNT_AUTO, label: 'Auto bins' },
        ...NUMBER_PRESETS.map((value) => ({ value, label: `${value} bins` })),
    ]

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        data-attr="funnel-bin-filter"
                        data-quill
                        disabled={!!editingDisabledReason}
                        title={editingDisabledReason ?? undefined}
                    >
                        <IconGraph />
                        {label}
                    </Button>
                }
            />
            <PopoverContent align="end" className="w-auto p-0 overflow-hidden">
                <div className="flex w-40 flex-col gap-px p-2">
                    {presets.map((preset) => (
                        <Button
                            key={String(preset.value)}
                            variant="default"
                            size="sm"
                            left
                            className="w-full justify-start"
                            aria-selected={preset.value === selectedValue}
                            onClick={() => {
                                setOpen(false)
                                setBinCount(preset.value)
                            }}
                            data-attr={`funnel-bin-preset-${preset.value}`}
                        >
                            {preset.label}
                        </Button>
                    ))}
                    <div className="flex items-center gap-1 px-2 py-1">
                        <Input
                            type="number"
                            min={MIN}
                            max={MAX}
                            value={numericBinCount}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => {
                                const parsedCount = parseInt(e.target.value)
                                if (parsedCount) {
                                    setBinCount(parsedCount)
                                }
                            }}
                            className="h-6 w-16"
                            aria-label="Custom bin count"
                            data-attr="funnel-bin-custom-count"
                        />
                        <span className="text-xs whitespace-nowrap">bins</span>
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    )
}
