import './CohortField.scss'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import React, { useEffect, useMemo } from 'react'
import { LemonSpacer } from 'lib/components/LemonRow'
import { cohortFieldLogic } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import { useActions, useValues } from 'kea'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { LemonTaxonomicPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import {
    CohortFieldBaseProps,
    CohortNumberFieldProps,
    CohortSelectorFieldProps,
    CohortTaxonomicFieldProps,
    CohortTextFieldProps,
} from 'scenes/cohorts/CohortFilters/types'

let uniqueMemoizedIndex = 0

const useCohortLogic = (props: CohortFieldBaseProps): { logic: ReturnType<typeof cohortFieldLogic.build> } => {
    const cohortFilterLogicKey = useMemo(
        () => props.cohortFilterLogicKey || `cohort-filter-${uniqueMemoizedIndex++}`,
        [props.cohortFilterLogicKey]
    )
    const logic = cohortFieldLogic({ ...props, cohortFilterLogicKey })
    const { setValue } = useActions(logic)

    useEffect(() => {
        setValue(props.value)
    }, [props.value])
    return {
        logic,
    }
}

export function CohortSelectorField({
    cohortFilterLogicKey,
    value,
    fieldOptionGroupTypes,
    placeholder,
    onChange: _onChange,
}: CohortSelectorFieldProps): JSX.Element {
    const { logic } = useCohortLogic({
        cohortFilterLogicKey,
        value,
        fieldOptionGroupTypes,
        onChange: _onChange,
    })

    const { fieldOptionGroups, currentOption } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <LemonButtonWithPopup
            type="secondary"
            sideIcon={undefined}
            popup={{
                overlay: (
                    <div className="CohortField__dropdown">
                        {fieldOptionGroups.map(({ label, type: groupKey, values }, i) => (
                            <div key={i}>
                                {i !== 0 && <LemonSpacer />}
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

export function CohortTaxonomicField({
    cohortFilterLogicKey,
    value,
    taxonomicGroupType = TaxonomicFilterGroupType.Events,
    taxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    onChange: _onChange,
    onTaxonomicGroupChange,
}: CohortTaxonomicFieldProps): JSX.Element {
    const { logic } = useCohortLogic({
        cohortFilterLogicKey,
        value,
        onChange: _onChange,
    })

    const { onChange } = useActions(logic)

    return (
        <LemonTaxonomicPopup
            type="secondary"
            groupType={taxonomicGroupType}
            value={value as TaxonomicFilterValue}
            onChange={(v, g) => {
                onChange(v)
                onTaxonomicGroupChange?.(g)
            }}
            groupTypes={taxonomicGroupTypes}
            placeholder="Choose event"
        />
    )
}

export function CohortTextField({ value }: CohortTextFieldProps): JSX.Element {
    return <span className="CohortField__CohortTextField">{value}</span>
}

export function CohortNumberField({
    cohortFilterLogicKey,
    value,
    onChange: _onChange,
}: CohortNumberFieldProps): JSX.Element {
    const { logic } = useCohortLogic({
        cohortFilterLogicKey,
        value,
        onChange: _onChange,
    })
    const { onChange } = useActions(logic)

    return (
        <LemonInput
            type="number"
            value={value ?? undefined}
            onChange={(nextNumber) => {
                onChange(nextNumber)
            }}
            className="CohortField__CohortNumberField"
        />
    )
}
