// This will be integrated into Kea soon... It's just faster to iterate here.

import { kea as regularKea, useValues as useRegularValues } from 'kea'

type BlankLogic = {
    actions?: any
    actionCreators?: any
    actionTypes?: any
    reducers?: any
    selectors?: any
    listeners?: any
    values?: any
    __selectorTypeHelp?: any
}

type ReducerActions<LogicType extends BlankLogic, ReducerType> = {
    [K in keyof LogicType['actions']]?: (
        state: any,
        payload: ReturnType<LogicType['actions'][K]>['payload'],
    ) => ReducerType
}
type ReducerDefinitions<LogicType extends BlankLogic> = {
    [K in keyof LogicType['reducers']]?:
        | [ReturnType<LogicType['reducers'][K]>, ReducerActions<LogicType, ReturnType<LogicType['reducers'][K]>>]
        | ReducerActions<LogicType, ReturnType<LogicType['reducers'][K]>>
}
type Selector = (state?: any, props?: any) => any

type SelectorDefinition<Selectors, S extends Selector, SelectorFunction extends any> = [
    (
        s: Selectors,
    ) =>
        | []
        | [Selector]
        | [Selector, Selector]
        | [Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
        | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector],
    SelectorFunction,
]

type SelectorDefinitions<LogicType extends BlankLogic> = {
    [K in keyof LogicType['selectors']]?: SelectorDefinition<
        LogicType['selectors'],
        LogicType['selectors'][K],
        LogicType['__selectorTypeHelp'][K]
    >
}

type ListenerDefinitions<LogicType extends BlankLogic> = {
    [K in keyof LogicType['actions']]?:
        | ((
              payload: ReturnType<LogicType['actions'][K]>['payload'],
              breakpoint: (() => void) | ((ms: number) => Promise<void>),
              action: ReturnType<LogicType['actions'][K]>,
              previousState: any,
          ) => void | Promise<void>)
        | (() => void | Promise<void>)
}
type LogicInput<LogicType> = {
    path?: any
    constants?: any
    actions?: (logic: LogicType) => any | any
    reducers?: ReducerDefinitions<LogicType> | ((logic: LogicType) => ReducerDefinitions<LogicType>)
    events?: (logic: LogicType) => any | any
    selectors?: SelectorDefinitions<LogicType> | ((logic: LogicType) => SelectorDefinitions<LogicType>)
    listeners?: ListenerDefinitions<LogicType> | ((logic: LogicType) => ListenerDefinitions<LogicType>)
    loaders?: any
}

export function kea<LogicType>(input: LogicInput<LogicType>): LogicType {
    return regularKea(input)
}
export function useValues<L extends BlankLogic>(logic: L): L['values'] {
    return useRegularValues(logic)
}
