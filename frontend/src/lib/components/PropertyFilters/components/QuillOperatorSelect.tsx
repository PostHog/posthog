import { QuillSelect, QuillSelectGroup } from 'lib/components/QuillSelect/QuillSelect'
import { allOperatorsMapping, isOperatorSemver } from 'lib/utils/operators'

import { PropertyOperator } from '~/types'

export interface QuillOperatorSelectProps {
    operator: PropertyOperator
    operators: PropertyOperator[]
    onChange: (operator: PropertyOperator) => void
    className?: string
    defaultOpen?: boolean
}

function toOption(op: PropertyOperator): { value: PropertyOperator; label: string } {
    return { value: op || PropertyOperator.Exact, label: allOperatorsMapping[op || PropertyOperator.Exact] }
}

export function QuillOperatorSelect({
    operator,
    operators,
    onChange,
    className,
    defaultOpen,
}: QuillOperatorSelectProps): JSX.Element {
    const standard = operators.filter((op) => !isOperatorSemver(op))
    const semver = operators.filter(isOperatorSemver)
    const groups: QuillSelectGroup<PropertyOperator>[] = [
        ...(standard.length ? [{ options: standard.map(toOption) }] : []),
        ...(semver.length ? [{ label: 'Semver operators', options: semver.map(toOption) }] : []),
    ]

    return (
        <QuillSelect<PropertyOperator>
            options={groups}
            value={operator || PropertyOperator.Exact}
            placeholder="Property key"
            fullWidth
            onChange={(op) => {
                op && onChange(op)
            }}
            className={className}
            defaultOpen={defaultOpen}
        />
    )
}
