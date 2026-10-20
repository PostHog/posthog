import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { allOperatorsMapping, isOperatorSemver } from 'lib/utils/operators'

import { PropertyOperator } from '~/types'

import type { OperatorSelectProps } from './OperatorValueSelect'

function toOption(op: PropertyOperator): { label: JSX.Element; value: PropertyOperator } {
    return {
        label: <span className="operator-value-option">{allOperatorsMapping[op || PropertyOperator.Exact]}</span>,
        value: op || PropertyOperator.Exact,
    }
}

export function LemonOperatorSelect({
    operator,
    operators,
    onChange,
    className,
    size,
    startVisible,
}: OperatorSelectProps): JSX.Element {
    const hasSemver = operators.some(isOperatorSemver)
    const options: LemonSelectSection<PropertyOperator>[] | { label: JSX.Element; value: PropertyOperator }[] =
        hasSemver
            ? [
                  ...(operators.some((op) => !isOperatorSemver(op))
                      ? [{ options: operators.filter((op) => !isOperatorSemver(op)).map(toOption) }]
                      : []),
                  {
                      title: 'Semver operators',
                      footer: (
                          <div className="mx-2 my-1">
                              <Link
                                  to="https://posthog.com/docs/data/property-filters#semver-operators"
                                  target="_blank"
                                  className="text-xs"
                              >
                                  Learn more
                              </Link>
                          </div>
                      ),
                      options: operators.filter(isOperatorSemver).map(toOption),
                  },
              ]
            : operators.map(toOption)

    return (
        <LemonSelect
            options={options}
            value={operator || '='}
            placeholder="Property key"
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
            fullWidth
            onChange={(op) => {
                op && onChange(op)
            }}
            className={className}
            size={size}
            menu={{
                closeParentPopoverOnClickInside: false,
                ...(hasSemver ? { className: '!max-h-[400px]' } : {}),
            }}
            startVisible={startVisible}
        />
    )
}
