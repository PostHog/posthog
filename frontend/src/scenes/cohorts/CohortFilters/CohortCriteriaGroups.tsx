import './CohortCriteriaGroups.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'
import { Field as KeaField } from 'kea-forms/lib/components'

import { IconCopy, IconPlusSmall, IconTrash } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { alphabet } from 'lib/utils'
import { CohortCriteriaRowBuilder } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { CohortLogicProps, cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { criteriaToBehavioralFilterType, isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'

export function CohortCriteriaGroups(logicProps: CohortLogicProps): JSX.Element {
    const { cohort } = useValues(cohortEditLogic)
    const { setInnerGroupType, duplicateFilter, removeFilter, addFilter } = useActions(cohortEditLogic)

    return (
        <>
            {cohort.filters.properties.values.map((group, groupIndex) =>
                isCohortCriteriaGroup(group) ? (
                    <Group key={group.sort_key ?? groupIndex} name={['filters', 'properties', 'values', groupIndex]}>
                        {groupIndex !== 0 && (
                            <div className="CohortCriteriaGroups__matching-group__logical-divider">
                                {cohort.filters.properties.type}
                            </div>
                        )}
                        <KeaField
                            name="id"
                            template={({ error, kids }) => {
                                return (
                                    <div
                                        className={clsx(
                                            'CohortCriteriaGroups__matching-group',
                                            error && `CohortCriteriaGroups__matching-group--error`
                                        )}
                                    >
                                        <div className="flex flex-nowrap items-center px-4">
                                            <Lettermark name={alphabet[groupIndex]} color={LettermarkColor.Gray} />
                                            <AndOrFilterSelect
                                                prefix="Match persons against"
                                                suffix={['criterion', 'criteria']}
                                                onChange={(value) => setInnerGroupType(value, groupIndex)}
                                                value={group.type}
                                            />
                                            <div className="flex-1 min-w-[0.5rem]" />
                                            <LemonButton
                                                icon={<IconCopy />}
                                                onClick={() => duplicateFilter(groupIndex)}
                                            />
                                            {cohort.filters.properties.values.length > 1 && (
                                                <LemonButton
                                                    icon={<IconTrash />}
                                                    onClick={() => removeFilter(groupIndex)}
                                                />
                                            )}
                                        </div>
                                        <LemonDivider className="my-4" />
                                        {error && (
                                            <LemonBanner className="m-2" type="error">
                                                {error}
                                            </LemonBanner>
                                        )}
                                        {kids}
                                    </div>
                                )
                            }}
                        >
                            <>
                                {group.values.map((criteria, criteriaIndex) => {
                                    return isCohortCriteriaGroup(criteria) ? null : (
                                        <Group
                                            key={criteria.sort_key ?? criteriaIndex}
                                            name={['values', criteriaIndex]}
                                        >
                                            <CohortCriteriaRowBuilder
                                                id={logicProps.id}
                                                groupIndex={groupIndex}
                                                index={criteriaIndex}
                                                logicalOperator={group.type}
                                                criteria={criteria}
                                                type={criteriaToBehavioralFilterType(criteria)}
                                                hideDeleteIcon={group.values.length <= 1}
                                            />
                                            {criteriaIndex === group.values.length - 1 && (
                                                <div className="m-3">
                                                    <LemonButton
                                                        data-attr="cohort-add-filter-group-criteria"
                                                        type="secondary"
                                                        onClick={() => addFilter(groupIndex)}
                                                        icon={<IconPlusSmall />}
                                                    >
                                                        Add criteria
                                                    </LemonButton>
                                                </div>
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
                data-attr="cohort-add-filter-group"
                className="mb-4 mt-4"
                type="secondary"
                onClick={() => addFilter()}
                icon={<IconPlusSmall />}
                fullWidth
            >
                Add criteria group
            </LemonButton>
        </>
    )
}
