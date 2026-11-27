import { IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Input,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import type { WorkloadConditionRow } from './workloadConditionPresets'

interface ConditionOptionGroup {
    title: string
    options: { value: string; label: string }[]
}

interface ConditionRowView {
    row: WorkloadConditionRow
    /** The select's value for this row. */
    value: string
    takesValue: boolean
    placeholder?: string
    helpText: string
}

export function QuillWorkloadConditionRows({
    rows,
    options,
    onChoose,
    onUpdate,
    onRemove,
    onAdd,
}: {
    rows: ConditionRowView[]
    options: ConditionOptionGroup[]
    onChoose: (index: number, value: string) => void
    onUpdate: (index: number, row: WorkloadConditionRow) => void
    onRemove: (index: number) => void
    onAdd: () => void
}): JSX.Element {
    const items = options.flatMap((group) => group.options)

    return (
        <div className="flex flex-col gap-2 w-full">
            {rows.map(({ row, value, takesValue, placeholder, helpText }, index) => (
                <div key={index} className="flex flex-col gap-1">
                    <div className="flex flex-wrap gap-2 items-start">
                        <Select
                            items={items}
                            value={value}
                            onValueChange={(next: string | null) => {
                                if (next) {
                                    onChoose(index, next)
                                }
                            }}
                        >
                            <SelectTrigger
                                className="min-w-60 flex-1"
                                aria-label="Condition"
                                data-attr="workload-trust-policy-condition-preset"
                            >
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {options.map((group) => (
                                    <SelectGroup key={group.title}>
                                        <SelectGroupLabel>{group.title}</SelectGroupLabel>
                                        {group.options.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectGroup>
                                ))}
                            </SelectContent>
                        </Select>
                        {takesValue ? (
                            <Input
                                value={row.value}
                                onChange={(event) => onUpdate(index, { ...row, value: event.target.value })}
                                placeholder={placeholder}
                                aria-label="Condition value"
                                className="min-w-40 flex-1"
                                data-attr="workload-trust-policy-condition-value"
                            />
                        ) : null}
                        <Button
                            size="icon"
                            aria-label="Remove this condition"
                            tooltip="Remove this condition"
                            onClick={() => onRemove(index)}
                            data-attr="workload-trust-policy-condition-remove"
                        >
                            <IconTrash />
                        </Button>
                    </div>
                    {helpText && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {helpText}
                        </Text>
                    )}
                </div>
            ))}
            <div>
                <Button variant="outline" onClick={onAdd} data-attr="workload-trust-policy-condition-add">
                    <IconPlus />
                    Add condition
                </Button>
            </div>
        </div>
    )
}
