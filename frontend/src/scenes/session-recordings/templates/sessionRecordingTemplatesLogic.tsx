import clsx from 'clsx'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
    ReplayTemplateCategory,
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
    // one card can be in multiple categories,
    // key on the category so that multiple instances of the same card are isolated
    category: ReplayTemplateCategory
}

export const sessionReplayTemplatesLogic = kea<sessionReplayTemplatesLogicType>([
    path(() => ['scenes', 'session-recordings', 'templates', 'sessionReplayTemplatesLogic']),
    props({} as ReplayTemplateLogicPropsType),
    key((props) => `${props.category}-${props.template.key}`),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setVariables: (variables?: ReplayTemplateVariableType[]) => ({ variables }),
        setVariable: (variable: ReplayTemplateVariableType) => ({ variable }),
        resetVariable: (variable: ReplayTemplateVariableType) => ({ variable }),
        navigate: true,
        showVariables: true,
        hideVariables: true,
    }),
    reducers(({ props, values }) => ({
        variables: [
            props.template.variables ?? [],
            {
                persist: true,
                storageKey: clsx(
                    'session-recordings.templates.variables',
                    values.currentTeam?.id,
                    props.category,
                    props.template.key
                ),
            },
            {
                setVariables: (_, { variables }) => variables ?? [],
                setVariable: (state, { variable }) =>
                    state.map((v) => (v.key === variable.key ? { ...variable, touched: true } : v)),
                resetVariable: (state, { variable }) =>
                    state.map((v) => (v.key === variable.key ? { ...variable, touched: false } : v)),
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
                        if (
                            ['snapshot_source', 'event', 'person-property'].includes(variable.type) &&
                            variable.filterGroup
                        ) {
                            return variable.filterGroup
                        }
                        return undefined
                    })
                    .filter((filter): filter is UniversalFiltersGroupValue => filter !== undefined)

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
                    // TODO this should set order on the filter group after https://github.com/PostHog/posthog/pull/25701
                }
                return filterGroup
            },
        ],
        canApplyFilters: [
            (s) => [s.variables, s.areAnyVariablesTouched],
            (variables, areAnyVariablesTouched) => areAnyVariablesTouched || variables.length === 0,
        ],
        areAnyVariablesTouched: [
            (s) => [s.variables],
            (variables) => variables.some((v) => v.touched) || variables.some((v) => v.noTouch),
        ],
        editableVariables: [(s) => [s.variables], (variables) => variables.filter((v) => !v.noTouch)],
    }),
    listeners(({ values, props }) => ({
        navigate: () => {
            posthog.capture('session replay template used', {
                template: props.template.key,
                category: props.category,
            })
            const filterGroup = values.variables.length > 0 ? values.filterGroup : undefined
            router.actions.push(urls.replay(ReplayTabs.Home, filterGroup, undefined, props.template.order))
        },
    })),
    events(({ actions, props, values }) => ({
        afterMount: () => {
            if (values.variables.length === 0) {
                actions.setVariables(props.template.variables)
            }
        },
    })),
])
