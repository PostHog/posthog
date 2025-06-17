import { LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import {
    genericOperatorToHumanName,
    operatorToHumanName,
    propertyValueToHumanName,
} from 'lib/components/DefinitionPopover/utils'
import { pluralize } from 'lib/utils'
import { BEHAVIORAL_TYPE_TO_LABEL } from 'scenes/cohorts/CohortFilters/constants'
import {
    COHORT_MATCHING_DAYS,
    criteriaToBehavioralFilterType,
    criteriaToHumanSentence,
    isCohortCriteriaGroup,
} from 'scenes/cohorts/cohortUtils'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyCohortCriteriaType, CohortType, FilterLogicalOperator } from '~/types'

import { PropertyKeyInfo } from '../PropertyKeyInfo'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'

const MAX_CRITERIA_GROUPS = 2
const MAX_CRITERIA = 2

export function CohortPopoverInfo({ cohort }: { cohort: CohortType }): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    const { actionsById } = useValues(actionsModel)

    if (!cohort) {
        return null
    }
    return cohort.filters?.properties?.values?.length ? (
        <>
            <LemonDivider className="DefinitionPopover my-2" />
            {cohort.filters.properties.values.slice(0, MAX_CRITERIA_GROUPS).map(
                (cohortGroup, cohortGroupIndex) =>
                    isCohortCriteriaGroup(cohortGroup) && (
                        <DefinitionPopover.Section key={cohortGroupIndex}>
                            <DefinitionPopover.Card
                                title={`Match persons against ${
                                    cohortGroup.type === FilterLogicalOperator.Or ? 'any' : 'all'
                                } criteria`}
                                value={
                                    <ul>
                                        {cohortGroup.values.slice(0, MAX_CRITERIA).map((criteria, criteriaIndex) => (
                                            <>
                                                <li>
                                                    {BEHAVIORAL_TYPE_TO_LABEL[
                                                        criteriaToBehavioralFilterType(
                                                            criteria as AnyCohortCriteriaType
                                                        )
                                                    ]?.label ?? 'Unknown criteria'}
                                                </li>
                                                <ul>
                                                    <li key={criteriaIndex}>
                                                        <span>
                                                            {criteriaToHumanSentence(
                                                                criteria as AnyCohortCriteriaType,
                                                                cohortsById,
                                                                actionsById
                                                            )}
                                                        </span>
                                                    </li>
                                                </ul>
                                            </>
                                        ))}
                                        {cohortGroup.values.length > MAX_CRITERIA && (
                                            <li>
                                                <span>{cohortGroup.values.length - MAX_CRITERIA} more criteria</span>
                                            </li>
                                        )}
                                    </ul>
                                }
                            />
                            {cohortGroupIndex <
                                Math.min(cohort.filters.properties.values.length, MAX_CRITERIA_GROUPS) - 1 && (
                                <DefinitionPopover.HorizontalLine
                                    className="mt-1 mb-3"
                                    label={cohort.filters.properties.type}
                                />
                            )}
                            {cohort.filters.properties.values.length > MAX_CRITERIA_GROUPS &&
                                cohortGroupIndex === MAX_CRITERIA_GROUPS - 1 && (
                                    <DefinitionPopover.HorizontalLine
                                        className="mt-1 mb-3"
                                        label={`${
                                            cohort.filters.properties.values.length - MAX_CRITERIA_GROUPS
                                        } more criteria ${pluralize(
                                            cohort.filters.properties.values.length - MAX_CRITERIA_GROUPS,
                                            'group',
                                            'groups',
                                            false
                                        )}`}
                                    />
                                )}
                        </DefinitionPopover.Section>
                    )
            )}
        </>
    ) : (
        <>
            {(cohort.groups?.length || 0 > 0) && <LemonDivider className="DefinitionPopover my-2" />}
            {cohort.groups &&
                cohort.groups.map((group, index) => (
                    <DefinitionPopover.Section key={index}>
                        {'action_id' in group ? (
                            <DefinitionPopover.Card
                                title="Match persons who performed"
                                value={
                                    <ul>
                                        <li>
                                            <span>
                                                <PropertyKeyInfo
                                                    value={group.event_id}
                                                    type={TaxonomicFilterGroupType.Events}
                                                />
                                                {operatorToHumanName(group.count_operator)} in the last{' '}
                                                {COHORT_MATCHING_DAYS[group.days as '1' | '7' | '14' | '30']}
                                            </span>
                                        </li>
                                    </ul>
                                }
                            />
                        ) : (
                            <DefinitionPopover.Card
                                title="Match persons with properties"
                                value={
                                    <ul>
                                        {group.properties &&
                                            group.properties.map((property, propIndex) => (
                                                <li key={propIndex}>
                                                    <span>
                                                        <PropertyKeyInfo
                                                            value={property.key}
                                                            type={TaxonomicFilterGroupType.PersonProperties}
                                                        />
                                                        {genericOperatorToHumanName(property)}
                                                        <code>{propertyValueToHumanName(property.value)}</code>
                                                    </span>
                                                </li>
                                            ))}
                                    </ul>
                                }
                            />
                        )}
                        {cohort.groups && index < cohort.groups.length - 1 && (
                            <DefinitionPopover.HorizontalLine className="mt-1 mb-3" label="OR" />
                        )}
                    </DefinitionPopover.Section>
                ))}
        </>
    )
}
