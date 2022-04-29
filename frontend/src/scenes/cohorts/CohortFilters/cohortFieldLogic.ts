import { kea } from 'kea'
import { FieldOptionsType, FieldValues } from 'scenes/cohorts/CohortFilters/types'
import { FIELD_VALUES } from 'scenes/cohorts/CohortFilters/constants'
import { groupsModel } from '~/models/groupsModel'
import { ActorGroupType, AnyCohortCriteriaType } from '~/types'
import type { cohortFieldLogicType } from './cohortFieldLogicType'
import { cleanBehavioralTypeCriteria } from 'scenes/cohorts/CohortFilters/cohortUtils'

export interface CohortFieldLogicProps {
    cohortFilterLogicKey: string
    fieldKey: keyof AnyCohortCriteriaType
    criteria: AnyCohortCriteriaType
    onChange?: (newField: AnyCohortCriteriaType) => void
    /* Only used for selector fields */
    fieldOptionGroupTypes?: FieldOptionsType[]
}

export const cohortFieldLogic = kea<cohortFieldLogicType<CohortFieldLogicProps>>({
    path: ['scenes', 'cohorts', 'CohortFilters', 'cohortFieldLogic'],
    key: (props) => `${props.cohortFilterLogicKey}`,
    props: {} as CohortFieldLogicProps,
    connect: {
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
    },
    actions: {
        onChange: (newField: AnyCohortCriteriaType) => ({ newField }),
    },
    reducers: ({ props }) => ({
        value: [
            props.criteria?.[props.fieldKey] ?? (null as string | number | boolean | null | undefined),
            {
                onChange: (state, { newField }) => newField[props.fieldKey] ?? state,
            },
        ],
    }),
    selectors: {
        fieldOptionGroups: [
            (s) => [(_, props) => props.fieldOptionGroupTypes, s.groupTypes, s.aggregationLabel],
            (fieldOptionGroupTypes, groupTypes, aggregationLabel): FieldValues[] => {
                const allGroups = {
                    ...FIELD_VALUES,
                    [FieldOptionsType.Actors]: {
                        label: 'Actors',
                        type: FieldOptionsType.Actors,
                        values: {
                            [ActorGroupType.Person]: {
                                label: 'Persons',
                            },
                            ...Object.fromEntries(
                                groupTypes.map((type) => [
                                    `${ActorGroupType.GroupPrefix}_${type.group_type_index}`,
                                    { label: aggregationLabel(type.group_type_index).plural },
                                ])
                            ),
                        },
                    },
                }
                return [...(fieldOptionGroupTypes?.map((type: FieldOptionsType) => allGroups[type]) ?? [])]
            },
        ],
        currentOption: [
            (s) => [s.fieldOptionGroups, s.value],
            (fieldOptionGroups, value) =>
                value && typeof value === 'string'
                    ? fieldOptionGroups.reduce((accumulator, group) => ({ ...accumulator, ...group.values }), {})?.[
                          value
                      ]
                    : null,
        ],
    },
    listeners: ({ props }) => ({
        onChange: ({ newField }) => {
            props.onChange?.(cleanBehavioralTypeCriteria(newField))
        },
    }),
})
