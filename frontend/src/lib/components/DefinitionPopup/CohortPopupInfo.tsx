import React from 'react'
import { CohortType } from '~/types'
import { DefinitionPopup } from 'lib/components/DefinitionPopup/DefinitionPopup'
import {
    eventToHumanName,
    genericOperatorToHumanName,
    operatorToHumanName,
    propertyValueToHumanName,
} from 'lib/components/DefinitionPopup/utils'
import { COHORT_MATCHING_DAYS } from 'scenes/cohorts/MatchCriteriaSelector'

export function CohortPopupInfo({ entity }: { entity: CohortType }): JSX.Element | null {
    if (!entity) {
        return null
    }
    return (
        <>
            {entity.groups &&
                entity.groups.map((group, index) => (
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
                        {entity.groups && index < entity.groups.length - 1 && (
                            <DefinitionPopup.HorizontalLine style={{ marginTop: 4, marginBottom: 12 }}>
                                OR
                            </DefinitionPopup.HorizontalLine>
                        )}
                    </DefinitionPopup.Section>
                ))}
        </>
    )
}
