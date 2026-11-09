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

export function QuillOperatorSelect({
    operator,
    otherOperators,
    semverOperators,
    onChange,
    className,
    startVisible,
}: QuillOperatorSelectProps): JSX.Element {
    return (
        <Select<PropertyOperator>
            value={operator}
            onValueChange={(next: PropertyOperator | null) => next && onChange(next)}
            defaultOpen={startVisible}
        >
            <SelectTrigger render={<Button variant="outline" left />} className={cn('w-full min-w-0', className)}>
                <SelectValue className="truncate">
                    {(selected: PropertyOperator) => allOperatorsMapping[selected] ?? selected}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {otherOperators.map((op) => (
                    <SelectItem key={op} value={op}>
                        {allOperatorsMapping[op]}
                    </SelectItem>
                ))}
                {semverOperators.length > 0 && (
                    <>
                        {otherOperators.length > 0 && <SelectSeparator />}
                        <SelectGroup>
                            <SelectGroupLabel>Semver operators</SelectGroupLabel>
                            {semverOperators.map((op) => (
                                <SelectItem key={op} value={op}>
                                    {allOperatorsMapping[op]}
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </>
                )}
            </SelectContent>
        </Select>
    )
}
