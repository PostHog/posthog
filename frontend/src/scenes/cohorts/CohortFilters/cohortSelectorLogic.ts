import { kea } from 'kea'
import { LemonSelectOption, LemonSelectOptions } from 'lib/components/LemonSelect'
import { FilterGroupTypes, GroupOption } from 'scenes/cohorts/CohortFilters/types'
import type { cohortSelectorLogicType } from './cohortSelectorLogicType'
import { FILTER_GROUPS } from 'scenes/cohorts/CohortFilters/constants'
import { groupsModel } from '~/models/groupsModel'
import { ActorGroupType } from '~/types'

export interface CohortSelectorLogicProps {
    cohortFilterLogicKey: string
    value: string | number | null
    groupTypes?: FilterGroupTypes[]
    onChange?: (value: string | number | null, option?: LemonSelectOption, group?: LemonSelectOptions) => void
}

export const cohortSelectorLogic = kea<cohortSelectorLogicType<CohortSelectorLogicProps>>({
    path: ['scenes', 'cohorts', 'CohortFilters', 'cohortSelectorLogic'],
    key: (props) => `${props.cohortFilterLogicKey}`,
    props: {} as CohortSelectorLogicProps,
    connect: {
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
    },
    actions: {
        setValue: (value: string | number | null) => ({ value }),
        onChange: (value: string | number | null, option: LemonSelectOption, group: LemonSelectOptions) => ({
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
        groups: [
            (s) => [(_, props) => props.groupTypes, s.groupTypes, s.aggregationLabel],
            (propGroupTypes, groupTypes, aggregationLabel): GroupOption[] => {
                const allGroups = {
                    ...FILTER_GROUPS,
                    [FilterGroupTypes.Actors]: {
                        label: 'Actors',
                        type: FilterGroupTypes.Actors,
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
                return [...(propGroupTypes?.map((type: FilterGroupTypes) => allGroups[type]) ?? [])]
            },
        ],
        currentOption: [
            (s) => [s.groups, s.value],
            (groups, value) =>
                value
                    ? groups.reduce((accumulator, group) => ({ ...accumulator, ...group.values }), {})?.[value]
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
