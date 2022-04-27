import './CohortSelector.scss'
import { LemonButtonWithPopup } from 'lib/components/LemonButton'
import React, { useEffect, useMemo } from 'react'
import { LemonButton } from 'lib/components/LemonButton'
import { cohortSelectorLogic, CohortSelectorLogicProps } from 'scenes/cohorts/CohortFilters/cohortSelectorLogic'
import { useActions, useValues } from 'kea'
import { LemonDivider } from 'lib/components/LemonDivider'

export interface CohortSelectorProps extends CohortSelectorLogicProps {
    placeholder: string
}

let uniqueMemoizedIndex = 0

export function CohortSelector({
    cohortFilterLogicKey: _cohortFilterLogicKey,
    value,
    groupTypes,
    placeholder,
    onChange: _onChange,
}: CohortSelectorProps): JSX.Element {
    const cohortFilterLogicKey = useMemo(
        () => _cohortFilterLogicKey || `cohort-filter-${uniqueMemoizedIndex++}`,
        [_cohortFilterLogicKey]
    )
    const logicProps = {
        cohortFilterLogicKey,
        value,
        groupTypes,
        onChange: _onChange,
    }
    const logic = cohortSelectorLogic(logicProps)
    const { groups, currentOption } = useValues(logic)
    const { setValue, onChange } = useActions(logic)

    useEffect(() => {
        setValue(value)
    }, [value])

    return (
        <LemonButtonWithPopup
            type="secondary"
            sideIcon={undefined}
            popup={{
                overlay: (
                    <div className="CohortSelector__dropdown">
                        {groups.map(({ label, type: groupKey, values }, i) => (
                            <div key={i}>
                                {i !== 0 && <LemonDivider />}
                                <h5>{label}</h5>
                                {Object.entries(values).map(([key, option]) => (
                                    <LemonButton
                                        key={key}
                                        onClick={() => {
                                            onChange(key, option, values)
                                        }}
                                        type={key == value ? 'highlighted' : 'stealth'}
                                        fullWidth
                                        data-attr={`cohort-${groupKey}-${key}-type`}
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        ))}
                    </div>
                ),
            }}
        >
            {currentOption?.label || <span className="text-muted">{placeholder}</span>}
        </LemonButtonWithPopup>
    )
}
