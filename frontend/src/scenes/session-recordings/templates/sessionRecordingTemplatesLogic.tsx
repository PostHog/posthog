import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
    ReplayTemplateType,
    ReplayTemplateVariableType,
    UniversalFiltersGroupValue,
} from '~/types'

import type { sessionReplayTemplatesLogicType } from './sessionRecordingTemplatesLogicType'

const getPageviewFilterValue = (pageview: string): UniversalFiltersGroupValue => {
    return {
        key: 'visited_page',
        value: pageview,
        operator: PropertyOperator.IContains,
        type: PropertyFilterType.Recording,
    }
}

const getFlagFilterValue = (flag: string): UniversalFiltersGroupValue => {
    return {
        id: '$feature_flag_called',
        name: '$feature_flag_called',
        type: 'events',
        properties: [
            {
                key: `$feature/${flag}`,
                type: PropertyFilterType.Event,
                value: ['false'],
                operator: PropertyOperator.IsNot,
            },
            {
                key: `$feature/${flag}`,
                type: PropertyFilterType.Event,
                value: 'is_set',
                operator: PropertyOperator.IsSet,
            },
            {
                key: '$feature_flag',
                type: PropertyFilterType.Event,
                value: flag,
                operator: PropertyOperator.Exact,
            },
        ],
    }
}

export interface ReplayTemplateLogicPropsType {
    template: ReplayTemplateType
}

export const sessionReplayTemplatesLogic = kea<sessionReplayTemplatesLogicType>([
    path(() => ['scenes', 'session-recordings', 'templates', 'sessionReplayTemplatesLogic']),
    props({} as ReplayTemplateLogicPropsType),
    key((props) => props.template.key),
    actions({
        setVariables: (variables: ReplayTemplateVariableType[]) => ({ variables }),
        setVariable: (variable: ReplayTemplateVariableType) => ({ variable }),
        navigate: true,
        showVariables: true,
        hideVariables: true,
    }),
    reducers(({ props }) => ({
        variables: [
            props.template.variables,
            {
                setVariables: (_, { variables }) => variables,
                setVariable: (state, { variable }) =>
                    state.map((v) => (v.key === variable.key ? { ...variable, touched: true } : v)),
            },
        ],
        variablesVisible: [
            false,
            {
                showVariables: () => true,
                hideVariables: () => false,
            },
        ],
    })),
    selectors({
        filterGroup: [
            (s) => [s.variables],
            (variables) => {
                const filters = variables
                    .map((variable) => {
                        if (variable.type === 'pageview' && variable.value) {
                            return getPageviewFilterValue(variable.value)
                        }
                        if (variable.type === 'flag' && variable.value) {
                            return getFlagFilterValue(variable.value)
                        }
                        if (variable.type === 'event' && variable.filterGroup) {
                            return variable.filterGroup
                        }
                        return undefined
                    })
                    .filter((filter) => filter !== undefined)

                const filterGroup: Partial<RecordingUniversalFilters> = {
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: filters,
                            },
                        ],
                    },
                }
                return filterGroup
            },
        ],
        areAnyVariablesTouched: [
            (s) => [s.variables],
            (variables) => variables.some((v) => v.touched) || variables.some((v) => v.noTouch),
        ],
        editableVariables: [(s) => [s.variables], (variables) => variables.filter((v) => !v.noTouch)],
    }),
    listeners(({ values }) => ({
        navigate: () => {
            const filterGroup = values.variables.length > 0 ? values.filterGroup : undefined
            router.actions.push(urls.replay(ReplayTabs.Home, filterGroup))
        },
    })),
    events(({ actions, props }) => ({
        afterMount: () => {
            actions.setVariables(props.template.variables)
        },
    })),
])
