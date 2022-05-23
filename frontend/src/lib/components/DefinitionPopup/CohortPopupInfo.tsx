import React from 'react'
import { AnyCohortCriteriaType, CohortType, FilterLogicalOperator } from '~/types'
import { DefinitionPopup } from 'lib/components/DefinitionPopup/DefinitionPopup'
import {
    eventToHumanName,
    genericOperatorToHumanName,
    operatorToHumanName,
    propertyValueToHumanName,
} from 'lib/components/DefinitionPopup/utils'
import { COHORT_MATCHING_DAYS } from 'scenes/cohorts/MatchCriteriaSelector'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { criteriaToHumanSentence, isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'
import { pluralize } from 'lib/utils'

const MAX_CRITERIA_GROUPS = 2
const MAX_CRITERIA = 2

export function CohortPopupInfo({ cohort }: { cohort: CohortType }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!cohort) {
        return null
    }
    return !!featureFlags[FEATURE_FLAGS.COHORT_FILTERS] && cohort.filters?.properties ? (
        <>
            {(cohort.filters.properties?.values?.length || 0 > 0) && <DefinitionPopup.HorizontalLine />}
            {cohort.filters.properties.values.slice(0, MAX_CRITERIA_GROUPS).map(
                (cohortGroup, cohortGroupIndex) =>
                    isCohortCriteriaGroup(cohortGroup) && (
                        <DefinitionPopup.Section key={cohortGroupIndex}>
                            <DefinitionPopup.Card
                                title={`Match persons against ${
                                    cohortGroup.type === FilterLogicalOperator.Or ? 'any' : 'all'
                                } criteria`}
                                value={
                                    <ul>
                                        {cohortGroup.values.slice(0, MAX_CRITERIA).map((criteria, criteriaIndex) => (
                                            <li key={criteriaIndex}>
                                                <span>
                                                    {criteriaToHumanSentence(criteria as AnyCohortCriteriaType)}
                                                </span>
                                            </li>
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
                                <DefinitionPopup.HorizontalLine style={{ marginTop: 4, marginBottom: 12 }}>
                                    {cohort.filters.properties.type}
                                </DefinitionPopup.HorizontalLine>
                            )}
                            {cohort.filters.properties.values.length > MAX_CRITERIA_GROUPS &&
                                cohortGroupIndex === MAX_CRITERIA_GROUPS - 1 && (
                                    <DefinitionPopup.HorizontalLine style={{ marginTop: 4, marginBottom: 12 }}>
                                        {cohort.filters.properties.values.length - MAX_CRITERIA_GROUPS} more criteria{' '}
                                        {pluralize(
                                            cohort.filters.properties.values.length - MAX_CRITERIA_GROUPS,
                                            'group',
                                            'groups',
                                            false
                                        )}
                                    </DefinitionPopup.HorizontalLine>
                                )}
                        </DefinitionPopup.Section>
                    )
            )}
        </>
    ) : (
        <>
            {(cohort.groups?.length || 0 > 0) && <DefinitionPopup.HorizontalLine />}
            {cohort.groups &&
                cohort.groups.map((group, index) => (
                    <DefinitionPopup.Section key={index}>
                        {'action_id' in group ? (
                            <DefinitionPopup.Card
                                title="Match persons who performed"
                                value={
                                    <ul>
                                        <li>
                                            <span>
                                                <pre>{eventToHumanName(group.event_id)}</pre>
                                                {operatorToHumanName(group.count_operator)} in the last{' '}
                                                {COHORT_MATCHING_DAYS[group.days as '1' | '7' | '14' | '30']}
                                            </span>
                                        </li>
                                    </ul>
                                }
                            />
                        ) : (
                            <DefinitionPopup.Card
                                title="Match persons with properties"
                                value={
                                    <ul>
                                        {group.properties &&
                                            group.properties.map((property, propIndex) => (
                                                <li key={propIndex}>
                                                    <span>
                                                        <pre>{eventToHumanName(property.key)}</pre>
                                                        {genericOperatorToHumanName(property.operator)}
                                                        <pre>{propertyValueToHumanName(property.value)}</pre>
                                                    </span>
                                                </li>
                                            ))}
                                    </ul>
                                }
                            />
                        )}
                        {cohort.groups && index < cohort.groups.length - 1 && (
                            <DefinitionPopup.HorizontalLine style={{ marginTop: 4, marginBottom: 12 }}>
                                OR
                            </DefinitionPopup.HorizontalLine>
                        )}
                    </DefinitionPopup.Section>
                ))}
        </>
    )
}
