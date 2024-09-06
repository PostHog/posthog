import { actions, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { iframedToolbarBrowserLogic } from 'lib/components/IframedToolbarBrowser/iframedToolbarBrowserLogic'
import { PostHogAppToolbarEvent } from 'lib/components/IframedToolbarBrowser/utils'
import { isEmptyObject } from 'lib/utils'

import {
    ActionType,
    BaseMathType,
    DashboardTemplateVariableType,
    EntityType,
    EntityTypes,
    FilterType,
    Optional,
} from '~/types'

import type { dashboardTemplateVariablesLogicType } from './dashboardTemplateVariablesLogicType'

export interface DashboardTemplateVariablesLogicProps {
    variables: DashboardTemplateVariableType[]
}

const FALLBACK_EVENT = {
    id: '$pageview',
    math: 'dau',
    type: 'events',
}

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    props({ variables: [] } as DashboardTemplateVariablesLogicProps),
    connect({
        actions: [iframedToolbarBrowserLogic, ['toolbarMessageReceived']],
    }),
    actions({
        setVariables: (variables: DashboardTemplateVariableType[]) => ({ variables }),
        setVariable: (variableName: string, filterGroup: Optional<FilterType, 'type'>) => ({
            variable_name: variableName,
            filterGroup,
        }),
        setVariableFromAction: (variableName: string, action: ActionType) => ({ variableName, action }),
        setActiveVariableIndex: (index: number) => ({ index }),
        incrementActiveVariableIndex: true,
        possiblyIncrementActiveVariableIndex: true,
        resetVariable: (variableId: string) => ({ variableId }),
        goToNextUntouchedActiveVariableIndex: true,
    }),
    reducers({
        variables: [
            [] as DashboardTemplateVariableType[],
            {
                setVariables: (_, { variables }) => {
                    return variables.map((v) => {
                        if (v.default && !isEmptyObject(v.default)) {
                            return v
                        }
                        return { ...v, default: FALLBACK_EVENT } as unknown as DashboardTemplateVariableType
                    })
                },
                setVariable: (state, { variable_name: variableName, filterGroup }): DashboardTemplateVariableType[] => {
                    // There is only one type with contents at a time
                    // So iterate through the types to find the first one with contents
                    const typeWithContents: EntityType = Object.keys(filterGroup).filter(
                        (group) => (filterGroup[group as EntityType] || [])?.length > 0
                    )?.[0] as EntityType

                    if (!typeWithContents) {
                        return state
                    }

                    return state.map((v: DashboardTemplateVariableType) => {
                        if (
                            v.name === variableName &&
                            filterGroup?.[typeWithContents]?.length &&
                            filterGroup[typeWithContents][0]
                        ) {
                            return { ...v, default: filterGroup[typeWithContents][0], touched: true }
                        }
                        return { ...v }
                    })
                },
                resetVariable: (state, { variableId }) => {
                    return state.map((v: DashboardTemplateVariableType) => {
                        if (v.id === variableId) {
                            return { ...v, default: FALLBACK_EVENT, touched: false }
                        }
                        return { ...v }
                    })
                },
            },
        ],
        activeVariableIndex: [
            0,
            {
                setActiveVariableIndex: (_, { index }) => index,
                incrementActiveVariableIndex: (state) => state + 1,
            },
        ],
    }),
    selectors(() => ({
        activeVariable: [
            (s) => [s.variables, s.activeVariableIndex],
            (variables: DashboardTemplateVariableType[], activeVariableIndex: number) => {
                return variables[activeVariableIndex]
            },
        ],
        allVariablesAreTouched: [
            (s) => [s.variables],
            (variables: DashboardTemplateVariableType[]) => {
                return variables.every((v) => v.touched)
            },
        ],
    })),
    listeners(({ actions, props, values }) => ({
        possiblyIncrementActiveVariableIndex: () => {
            if (props.variables.length > 0 && values.activeVariableIndex < props.variables.length - 1) {
                actions.incrementActiveVariableIndex()
            }
        },
        goToNextUntouchedActiveVariableIndex: () => {
            let nextIndex = values.variables.findIndex((v, i) => !v.touched && i > values.activeVariableIndex)
            if (nextIndex !== -1) {
                actions.setActiveVariableIndex(nextIndex)
                return
            }
            if (nextIndex == -1) {
                nextIndex = values.variables.findIndex((v) => !v.touched)
                if (nextIndex == -1) {
                    nextIndex = values.activeVariableIndex
                }
            }
            actions.setActiveVariableIndex(nextIndex)
        },
        setVariableFromAction: ({ variableName, action }) => {
            const filterGroup: FilterType = {
                actions: [
                    // TODO: This needs a type
                    {
                        id: action.id,
                        math: BaseMathType.UniqueUsers,
                        name: action.name,
                        order: 0,
                        type: EntityTypes.ACTIONS,
                        selector: action.steps?.[0]?.selector,
                        href: action.steps?.[0]?.href,
                        url: action.steps?.[0]?.url,
                    },
                ],
            }
            actions.setVariable(variableName, filterGroup)
        },
        toolbarMessageReceived: ({ type, payload }) => {
            if (type === PostHogAppToolbarEvent.PH_NEW_ACTION_CREATED) {
                actions.setVariableFromAction(payload.action.name, payload.action as ActionType)
            }
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.variables !== oldProps.variables) {
            actions.setVariables(props.variables)
        }
    }),
])
