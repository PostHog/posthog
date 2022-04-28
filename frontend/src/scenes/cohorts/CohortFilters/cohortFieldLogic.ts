import { kea } from 'kea'
import { LemonSelectOption, LemonSelectOptions } from 'lib/components/LemonSelect'
import { FieldOptionsType, FieldValues } from 'scenes/cohorts/CohortFilters/types'
import { FIELD_VALUES } from 'scenes/cohorts/CohortFilters/constants'
import { groupsModel } from '~/models/groupsModel'
import { ActorGroupType } from '~/types'
import type { cohortFieldLogicType } from './cohortFieldLogicType'

export interface CohortFieldLogicProps {
    cohortFilterLogicKey: string
    value: string | number | null
    fieldOptionGroupTypes?: FieldOptionsType[]
    onChange?: (value: string | number | null, option?: LemonSelectOption, group?: LemonSelectOptions) => void
}

export const cohortFieldLogic = kea<cohortFieldLogicType<CohortFieldLogicProps>>({
    path: ['scenes', 'cohorts', 'CohortFilters', 'cohortFieldLogic'],
    key: (props) => `${props.cohortFilterLogicKey}`,
    props: {} as CohortFieldLogicProps,
    connect: {
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
    },
    actions: {
        setValue: (value: string | number | null) => ({ value }),
        onChange: (value: string | number | null, option?: LemonSelectOption, group?: LemonSelectOptions) => ({
            value,
            option,
            group,
        }),
    },
    reducers: {
        value: [
            null as string | number | null,
            {
                setValue: (_, { value }) => value,
            },
        ],
    },
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
                value
                    ? fieldOptionGroups.reduce((accumulator, group) => ({ ...accumulator, ...group.values }), {})?.[
                          value
                      ]
                    : null,
        ],
    },
    listeners: ({ props, actions }) => ({
        onChange: ({ value, option, group }) => {
            actions.setValue(value)
            props.onChange?.(value, option, group)
        },
    }),
})
