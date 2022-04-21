import { kea } from 'kea'
import { LemonSelectOption, LemonSelectOptions } from 'lib/components/LemonSelect'
import { FilterGroupTypes, GroupOption } from 'scenes/cohorts/CohortFilters/types'
import type { cohortSelectorLogicType } from './cohortSelectorLogicType'
import { FILTER_GROUPS } from 'scenes/cohorts/CohortFilters/options'

export interface CohortSelectorLogicProps {
    cohortFilterLogicKey: string
    value: keyof LemonSelectOptions | null
    groupTypes: FilterGroupTypes[]
    onChange?: (value: keyof LemonSelectOptions, option: LemonSelectOption, group: LemonSelectOptions) => void
}

export const cohortSelectorLogic = kea<cohortSelectorLogicType<CohortSelectorLogicProps>>({
    path: ['scenes', 'cohorts', 'CohortFilters', 'cohortSelectorLogic'],
    key: (props) => `${props.cohortFilterLogicKey}`,
    props: {} as CohortSelectorLogicProps,
    actions: {
        setValue: (value: keyof LemonSelectOptions | null) => ({ value }),
        onChange: (value: keyof LemonSelectOptions, option: LemonSelectOption, group: LemonSelectOptions) => ({
            value,
            option,
            group,
        }),
    },
    reducers: {
        value: [
            null as keyof LemonSelectOptions | null,
            {
                setValue: (_, { value }) => value,
            },
        ],
    },
    selectors: {
        groups: [
            () => [(_, props) => props.groupTypes],
            (groupTypes): GroupOption[] => groupTypes?.map((type: FilterGroupTypes) => FILTER_GROUPS[type]) ?? [],
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
