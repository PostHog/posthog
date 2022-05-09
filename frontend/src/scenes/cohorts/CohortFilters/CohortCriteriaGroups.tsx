import { criteriaToBehavioralFilterType, isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'
import { Group } from 'kea-forms'
import { Field as KeaField } from 'kea-forms/lib/components'
import clsx from 'clsx'
import { Row } from 'antd'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { alphabet } from 'lib/utils'
import { AndOrFilterSelect } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { LemonButton } from 'lib/components/LemonButton'
import { IconCopy, IconDelete, IconPlusMini } from 'lib/components/icons'
import { LemonDivider } from 'lib/components/LemonDivider'
import { AlertMessage } from 'lib/components/AlertMessage'
import { useActions, useValues } from 'kea'
import { cohortLogic } from 'scenes/cohorts/cohortLogic'
import { CohortCriteriaRowBuilder } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import React from 'react'

export function CohortCriteriaGroups(): JSX.Element {
    const { cohort } = useValues(cohortLogic)
    const { setInnerGroupType, duplicateFilter, removeFilter, addFilter } = useActions(cohortLogic)

    return (
        <>
            {cohort.filters.properties.values.map((group, groupIndex) =>
                isCohortCriteriaGroup(group) ? (
                    <Group key={groupIndex} name={['filters', 'properties', 'values', groupIndex]}>
                        {groupIndex !== 0 && (
                            <div className="cohort-detail__matching-group__logical-divider">{group.type}</div>
                        )}
                        <KeaField
                            name="id"
                            template={({ error, kids }) => {
                                return (
                                    <div
                                        className={clsx(
                                            'cohort-detail__matching-group',
                                            error && `cohort-detail__matching-group--error`
                                        )}
                                    >
                                        <Row align="middle" wrap={false} className="pl pr">
                                            <Lettermark name={alphabet[groupIndex]} color={LettermarkColor.Gray} />
                                            <AndOrFilterSelect
                                                prefix="Match persons against"
                                                suffix="criteria"
                                                onChange={(value) => setInnerGroupType(value, groupIndex)}
                                                value={group.type}
                                            />
                                            <div style={{ flex: 1, minWidth: '0.5rem' }} />
                                            <LemonButton
                                                icon={<IconCopy />}
                                                type="alt"
                                                onClick={() => duplicateFilter(groupIndex)}
                                            />
                                            {cohort.filters.properties.values.length > 1 && (
                                                <LemonButton
                                                    icon={<IconDelete />}
                                                    type="alt"
                                                    onClick={() => removeFilter(groupIndex)}
                                                />
                                            )}
                                        </Row>
                                        <LemonDivider large />
                                        {error && (
                                            <Row className="cohort-detail__matching-group__error-row">
                                                <AlertMessage type="error" style={{ width: '100%' }}>
                                                    <>{error}</>
                                                </AlertMessage>
                                            </Row>
                                        )}
                                        {kids}
                                    </div>
                                )
                            }}
                        >
                            <>
                                {group.values.map((criteria, criteriaIndex) => {
                                    return isCohortCriteriaGroup(criteria) ? null : (
                                        <Group key={criteriaIndex} name={['values', criteriaIndex]}>
                                            <CohortCriteriaRowBuilder
                                                groupIndex={groupIndex}
                                                index={criteriaIndex}
                                                logicalOperator={group.type}
                                                criteria={criteria}
                                                type={criteriaToBehavioralFilterType(criteria)}
                                                hideDeleteIcon={group.values.length <= 1}
                                            />
                                            {criteriaIndex === group.values.length - 1 && (
                                                <Row>
                                                    <LemonButton
                                                        data-attr={'cohort-add-filter-group-criteria'}
                                                        style={{ margin: '0.75rem' }}
                                                        type="secondary"
                                                        onClick={() => addFilter(groupIndex)}
                                                        icon={<IconPlusMini color="var(--primary)" />}
                                                    >
                                                        Add criteria
                                                    </LemonButton>
                                                </Row>
                                            )}
                                        </Group>
                                    )
                                })}
                            </>
                        </KeaField>
                    </Group>
                ) : null
            )}
            <LemonButton
                data-attr={`cohort-add-filter-group`}
                className="mb mt"
                type="secondary"
                onClick={() => addFilter()}
                icon={<IconPlusMini color="var(--primary)" />}
                fullWidth
            >
                Add criteria group
            </LemonButton>
        </>
    )
}
