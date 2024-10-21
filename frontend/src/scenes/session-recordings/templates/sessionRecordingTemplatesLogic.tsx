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
} from '~/types'

import type { sessionReplayTemplatesLogicType } from './sessionRecordingTemplatesLogicType'

// TODO IN THIS PR: What type should this be?
const getPageviewFilterValue = (pageview: string): Partial<any> => {
    return {
        key: 'visited_page',
        value: pageview,
        operator: PropertyOperator.IContains,
        type: PropertyFilterType.Recording,
    }
}

type ReplayTemplateLogicPropsType = {
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
            props.template.variables as ReplayTemplateVariableType[],
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
        areAnyVariablesTouched: [(s) => [s.variables], (variables) => variables.some((v) => v.touched)],
    }),
    listeners(({ values }) => ({
        navigate: () => {
            router.actions.push(urls.replay(ReplayTabs.Home, values.filterGroup))
        },
    })),
    events(({ actions, props }) => ({
        afterMount: () => {
            actions.setVariables(props.template.variables)
        },
    })),
])
