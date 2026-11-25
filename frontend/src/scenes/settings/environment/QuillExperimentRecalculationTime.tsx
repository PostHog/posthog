import { IconPlus, IconX } from '@posthog/icons'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { LemonSelectOption, LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'

function RecalculationTimeSelect({
    value,
    options,
    onChange,
    disabledReason,
    placeholder,
    dataAttr,
}: {
    value: string
    options: LemonSelectOption<string>[]
    onChange: (value: string) => void
    disabledReason?: string | null
    placeholder?: string
    dataAttr: string
}): JSX.Element {
    const leaves = options.filter((option): option is LemonSelectOptionLeaf<string> => 'value' in option)
    const items = leaves.map((option) => ({ value: option.value, label: option.label }))

    return (
        <Select items={items} value={value} onValueChange={(next) => next !== null && onChange(next as string)}>
            <SelectTrigger className="w-fit" disabledReason={disabledReason} data-attr={dataAttr}>
                <SelectValue placeholder={placeholder} />
            </SelectTrigger>
            <SelectContent>
                {leaves.map((option) => (
                    <SelectItem key={option.value} value={option.value} disabledReason={option.disabledReason}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

export function QuillExperimentRecalculationTime({
    times,
    allowSecondTime,
    optionsForIndex,
    selectedValue,
    onTimeChange,
    onAddSecondTime,
    onRemoveSecondTime,
    disabledReason,
}: {
    times: string[]
    allowSecondTime: boolean
    optionsForIndex: (index: number) => LemonSelectOption<string>[]
    selectedValue: (time: string) => string
    onTimeChange: (index: number, value: string) => void
    onAddSecondTime: () => void
    onRemoveSecondTime: () => void
    disabledReason?: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2">
            <RecalculationTimeSelect
                value={selectedValue(times[0])}
                options={optionsForIndex(0)}
                onChange={(value) => onTimeChange(0, value)}
                disabledReason={disabledReason}
                placeholder="Select recalculation time"
                dataAttr="team-experiment-recalculation-time"
            />
            {allowSecondTime &&
                (times.length > 1 ? (
                    <div className="flex flex-wrap items-center gap-1">
                        <RecalculationTimeSelect
                            value={selectedValue(times[1])}
                            options={optionsForIndex(1)}
                            onChange={(value) => onTimeChange(1, value)}
                            disabledReason={disabledReason}
                            dataAttr="team-experiment-second-recalculation-time"
                        />
                        <Button
                            size="icon"
                            aria-label="Remove second time"
                            tooltip="Remove second time"
                            onClick={onRemoveSecondTime}
                            disabledReason={disabledReason}
                            data-attr="team-experiment-remove-second-recalculation-time"
                        >
                            <IconX />
                        </Button>
                    </div>
                ) : (
                    <Button
                        onClick={onAddSecondTime}
                        disabledReason={disabledReason}
                        data-attr="team-experiment-add-second-recalculation-time"
                    >
                        <IconPlus />
                        Add second time
                    </Button>
                ))}
        </div>
    )
}
