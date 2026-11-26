import { IconX } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Item,
    ItemActions,
    ItemContent,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { CONDITION_TYPES, ConditionRule, GATEABLE_FIELDS, OPERATORS } from './approvalPolicyConditions'

export function QuillApprovalPolicyRuleRow({
    rule,
    onChange,
    onRemove,
}: {
    rule: ConditionRule
    onChange: (updates: Partial<ConditionRule>) => void
    onRemove: () => void
}): JSX.Element {
    const fieldConfig = GATEABLE_FIELDS[rule.field]
    const isNumeric = fieldConfig?.type === 'number'
    const fieldLabel = fieldConfig?.label || rule.field

    return (
        <Item variant="outline" size="sm">
            <ItemContent className="flex-row flex-wrap items-center gap-2">
                <ItemTitle className="whitespace-nowrap">{fieldLabel}</ItemTitle>
                <Select<string>
                    items={CONDITION_TYPES}
                    value={rule.type}
                    onValueChange={(value) => value && onChange({ type: value })}
                >
                    <SelectTrigger aria-label={`${fieldLabel} condition`}>
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {CONDITION_TYPES.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                {rule.type !== 'any_change' && isNumeric && (
                    <>
                        <Select<string>
                            items={OPERATORS}
                            value={rule.operator || '>'}
                            onValueChange={(value) => value && onChange({ operator: value })}
                        >
                            <SelectTrigger aria-label={`${fieldLabel} operator`}>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {OPERATORS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <InputGroup className="w-24">
                            <InputGroupInput
                                type="number"
                                aria-label={`${fieldLabel} threshold`}
                                min={rule.type === 'change_amount' ? -100 : 0}
                                max={100}
                                value={rule.value ?? ''}
                                onChange={(event) =>
                                    onChange({
                                        value: event.target.value === '' ? undefined : Number(event.target.value),
                                    })
                                }
                                placeholder="%"
                            />
                            <InputGroupAddon align="inline-end">
                                <InputGroupText>%</InputGroupText>
                            </InputGroupAddon>
                        </InputGroup>
                    </>
                )}
            </ItemContent>
            <ItemActions>
                <Button size="icon" aria-label="Remove rule" tooltip="Remove rule" onClick={onRemove}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
