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
    TemplateVariableStep,
} from '~/types'

import type { dashboardTemplateVariablesLogicType } from './dashboardTemplateVariablesLogicType'

export interface DashboardTemplateVariablesLogicProps {
    variables: DashboardTemplateVariableType[]
}

const FALLBACK_EVENT = {
    id: '$pageview',
    math: BaseMathType.UniqueUsers,
    type: EntityTypes.EVENTS,
}

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    props({ variables: [] } as DashboardTemplateVariablesLogicProps),
    connect(() => ({
        actions: [iframedToolbarBrowserLogic, ['toolbarMessageReceived', 'disableElementSelector']],
    })),
    actions({
        setVariables: (variables: DashboardTemplateVariableType[]) => ({ variables }),
        setVariable: (variableName: string, filterGroup: Optional<FilterType, 'type'>) => ({
            variable_name: variableName,
            filterGroup,
        }),
        setVariableFromAction: (variableName: string, action: ActionType) => ({ variableName, action }),
        setVariableForPageview: (variableName: string, url: string) => ({ variableName, url }),
        setVariableForScreenview: (variableName: string) => ({ variableName }),
        setActiveVariableIndex: (index: number) => ({ index }),
        incrementActiveVariableIndex: true,
        possiblyIncrementActiveVariableIndex: true,
        resetVariable: (variableId: string) => ({ variableId }),
        goToNextUntouchedActiveVariableIndex: true,
        setIsCurrentlySelectingElement: (isSelecting: boolean) => ({ isSelecting }),
        setActiveVariableCustomEventName: (customEventName?: string | null) => ({ customEventName }),
        maybeResetActiveVariableCustomEventName: true,
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
                            filterGroup?.[typeWithContents]?.[0]
                        ) {
                            return { ...v, default: filterGroup[typeWithContents]?.[0] || {}, touched: true }
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
        activeVariableCustomEventName: [
            null as string | null | undefined,
            {
                setActiveVariableCustomEventName: (_, { customEventName }) => customEventName,
            },
        ],
        isCurrentlySelectingElement: [
            false as boolean,
            {
                setIsCurrentlySelectingElement: (_, { isSelecting }) => isSelecting,
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
        hasTouchedAnyVariable: [
            (s) => [s.variables],
            (variables: DashboardTemplateVariableType[]) => {
                return variables.some((v) => v.touched)
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
            const originalVariableName = variableName.replace(/\s-\s\d+/g, '')
            const step: TemplateVariableStep = {
                id: action.id.toString(),
                math: BaseMathType.UniqueUsers,
                name: action.name,
                custom_name: originalVariableName,
                order: 0,
                type: EntityTypes.ACTIONS,
                selector: action.steps?.[0]?.selector,
                href: action.steps?.[0]?.href,
                url: action.steps?.[0]?.url,
            }
            const filterGroup: FilterType = {
                actions: [step],
            }
            actions.setVariable(originalVariableName, filterGroup)
            actions.setIsCurrentlySelectingElement(false)
        },
        setVariableForPageview: ({ variableName, url }) => {
            const step: TemplateVariableStep = {
                id: '$pageview',
                math: BaseMathType.UniqueUsers,
                type: EntityTypes.EVENTS,
                order: 0,
                name: '$pageview',
                custom_name: variableName,
                properties: [
                    {
                        key: '$current_url',
                        value: url,
                        operator: 'icontains',
                        type: 'event',
                    },
                ],
            }
            const filterGroup: FilterType = {
                events: [step],
            }
            actions.setVariable(variableName, filterGroup)
            actions.setIsCurrentlySelectingElement(false)
        },
        setVariableForScreenview: ({ variableName }) => {
            const step: TemplateVariableStep = {
                id: '$screenview',
                math: BaseMathType.UniqueUsers,
                type: EntityTypes.EVENTS,
                order: 0,
                name: '$screenview',
                custom_name: variableName,
            }
            const filterGroup: FilterType = {
                events: [step],
            }
            actions.setVariable(variableName, filterGroup)
            actions.setIsCurrentlySelectingElement(false)
        },
        toolbarMessageReceived: ({ type, payload }) => {
            if (type === PostHogAppToolbarEvent.PH_NEW_ACTION_CREATED) {
                actions.setVariableFromAction(payload.action.name, payload.action as ActionType)
                actions.disableElementSelector()
            }
        },
        maybeResetActiveVariableCustomEventName: () => {
            if (!values.activeVariable?.touched || !values.activeVariable?.default?.custom_event) {
                actions.setActiveVariableCustomEventName(null)
            } else if (values.activeVariable?.default?.custom_event) {
                actions.setActiveVariableCustomEventName(values.activeVariable.default.id)
            }
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.variables !== oldProps.variables) {
            actions.setVariables(props.variables)
        }
    }),
])
