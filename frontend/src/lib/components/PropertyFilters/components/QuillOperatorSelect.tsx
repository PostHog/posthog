import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
    cn,
} from '@posthog/quill'

import { allOperatorsMapping } from 'lib/utils/operators'

import { PropertyOperator } from '~/types'

export interface QuillOperatorSelectProps {
    operator: PropertyOperator
    otherOperators: PropertyOperator[]
    semverOperators: PropertyOperator[]
    onChange: (operator: PropertyOperator) => void
    className?: string
    startVisible?: boolean
}

// Rarely used in saved insights, so they sit behind "More options" along with the semver operators.
const RARE_OPERATORS = new Set<PropertyOperator>([
    PropertyOperator.NotRegex,
    PropertyOperator.StartsWith,
    PropertyOperator.NotStartsWith,
    PropertyOperator.EndsWith,
    PropertyOperator.NotEndsWith,
    PropertyOperator.GreaterThanOrEqual,
    PropertyOperator.LessThanOrEqual,
])

// The labels lead with a symbol ("= equals"), which reads as noise next to the words.
function operatorLabel(operator: PropertyOperator): string {
    const label = allOperatorsMapping[operator] ?? operator
    const [first, ...rest] = label.split(' ')
    return rest.length && !/[a-z0-9]/i.test(first) ? rest.join(' ') : label
}

export function QuillOperatorSelect({
    operator,
    otherOperators,
    semverOperators,
    onChange,
    className,
    startVisible,
}: QuillOperatorSelectProps): JSX.Element {
    const commonOperators = otherOperators.filter((op) => !RARE_OPERATORS.has(op))
    const rareOperators = otherOperators.filter((op) => RARE_OPERATORS.has(op))
    const hasMore = rareOperators.length > 0 || semverOperators.length > 0
    const currentIsRare = rareOperators.includes(operator) || semverOperators.includes(operator)
    const [showMore, setShowMore] = useState(false)
    const expanded = showMore || currentIsRare

    const items = (ops: PropertyOperator[]): JSX.Element[] =>
        ops.map((op) => (
            <SelectItem key={op} value={op}>
                {operatorLabel(op)}
            </SelectItem>
        ))

    return (
        <Select<PropertyOperator>
            value={operator}
            onValueChange={(next: PropertyOperator | null) => next && onChange(next)}
            onOpenChange={(open: boolean) => !open && setShowMore(false)}
            defaultOpen={startVisible}
        >
            <SelectTrigger render={<Button variant="outline" left />} className={cn('w-full min-w-0', className)}>
                <SelectValue className="truncate">
                    {(selected: PropertyOperator) => operatorLabel(selected)}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {items(commonOperators)}
                {hasMore && !expanded && (
                    <Button
                        size="row"
                        left
                        className="text-muted-foreground"
                        onClick={() => setShowMore(true)}
                        data-attr="operator-more-options"
                    >
                        More options
                        <IconChevronDown />
                    </Button>
                )}
                {expanded && rareOperators.length > 0 && (
                    <>
                        {commonOperators.length > 0 && <SelectSeparator />}
                        {items(rareOperators)}
                    </>
                )}
                {expanded && semverOperators.length > 0 && (
                    <>
                        <SelectSeparator />
                        <SelectGroup>
                            <SelectGroupLabel>Semver operators</SelectGroupLabel>
                            {items(semverOperators)}
                        </SelectGroup>
                    </>
                )}
            </SelectContent>
        </Select>
    )
}
