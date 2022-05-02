import './CohortField.scss'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import React, { useMemo } from 'react'
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
import { LemonDivider } from 'lib/components/LemonDivider'
import clsx from 'clsx'
import { Row } from 'antd'
import { Field as KeaField } from 'kea-forms'

let uniqueMemoizedIndex = 0

const useCohortLogic = (props: CohortFieldBaseProps): { logic: ReturnType<typeof cohortFieldLogic.build> } => {
    const cohortFilterLogicKey = useMemo(
        () => props.cohortFilterLogicKey || `cohort-filter-${uniqueMemoizedIndex++}`,
        [props.cohortFilterLogicKey]
    )
    const logic = cohortFieldLogic({ ...props, cohortFilterLogicKey })

    return {
        logic,
    }
}

export function CohortSelectorField({
    fieldKey,
    cohortFilterLogicKey,
    criteria,
    fieldOptionGroupTypes,
    placeholder,
    onChange: _onChange,
}: CohortSelectorFieldProps): JSX.Element {
    const { logic } = useCohortLogic({
        fieldKey: fieldKey,
        cohortFilterLogicKey,
        criteria,
        fieldOptionGroupTypes,
        onChange: _onChange,
    })

    const { fieldOptionGroups, currentOption, value } = useValues(logic)
    const { onChange } = useActions(logic)

    console.log('FIELD OPTIOS', fieldOptionGroups)

    return (
        <LemonButtonWithPopup
            type="secondary"
            className="CohortField"
            sideIcon={undefined}
            popup={{
                overlay: (
                    <div className="CohortField__dropdown">
                        {fieldOptionGroups.map(({ label, type: groupKey, values }, i) => (
                            <div key={i}>
                                {i !== 0 && <LemonDivider />}
                                <h5>{label}</h5>
                                {Object.entries(values).map(([_value, option]) => (
                                    <LemonButton
                                        key={_value}
                                        onClick={() => {
                                            onChange({ [fieldKey]: _value })
                                        }}
                                        type={_value == value ? 'highlighted' : 'stealth'}
                                        fullWidth
                                        data-attr={`cohort-${groupKey}-${_value}-type`}
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
    fieldKey,
    cohortFilterLogicKey,
    criteria,
    taxonomicGroupType = TaxonomicFilterGroupType.Events,
    taxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    placeholder = 'Choose event',
    onChange: _onChange,
}: CohortTaxonomicFieldProps): JSX.Element {
    const { logic } = useCohortLogic({
        fieldKey: fieldKey,
        criteria,
        cohortFilterLogicKey,
        onChange: _onChange,
    })

    const { value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <LemonTaxonomicPopup
            className="CohortField"
            type="secondary"
            groupType={taxonomicGroupType}
            value={value as TaxonomicFilterValue}
            onChange={(v, g) => {
                onChange({ [fieldKey]: v, event_type: g })
            }}
            groupTypes={taxonomicGroupTypes}
            placeholder={placeholder}
        />
    )
}

export function CohortTextField({ value }: CohortTextFieldProps): JSX.Element {
    return <span className={clsx('CohortField', 'CohortField__CohortTextField')}>{value}</span>
}

export function CohortNumberField({
    fieldKey,
    cohortFilterLogicKey,
    criteria,
    onChange: _onChange,
}: CohortNumberFieldProps): JSX.Element {
    const { logic } = useCohortLogic({
        fieldKey: fieldKey,
        cohortFilterLogicKey,
        criteria,
        onChange: _onChange,
    })
    const { value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <LemonInput
            type="number"
            value={(value as string | number) ?? undefined}
            onChange={(nextNumber) => {
                onChange({ [fieldKey]: Number(nextNumber) })
            }}
            className={clsx('CohortField', 'CohortField__CohortNumberField')}
        />
    )
}

// Kea field wrapper for cohort fields
export function CohortKeaField({
    children,
    name,
    className,
}: {
    children: React.ReactNode
    name: string
    className?: string
}): JSX.Element {
    return (
        <KeaField
            name={name}
            template={({ error, kids }) => {
                return (
                    <div className={clsx(className, error && `${className}--error`)}>
                        {kids}
                        <Row>
                            {error && (
                                <div
                                    style={{
                                        color: 'var(--danger)',
                                        marginTop: 16,
                                    }}
                                >
                                    {error}
                                </div>
                            )}
                        </Row>
                    </div>
                )
            }}
        >
            <div>{children}</div>
        </KeaField>
    )
}
