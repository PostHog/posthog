import { Action as ReduxAction } from 'redux'
import { BuiltLogic, LogicWrapper } from 'kea'

export type ActionToDispatch = string | ReduxAction | ((action: ReduxAction) => boolean)

export interface ExpectLogicMethods {
    toDispatchActions: (actions: ActionToDispatch[]) => ExpectLogicMethods
    toMatchValues: (values: Record<string, any>) => ExpectLogicMethods
    then: (callback?: (value: any) => void | Promise<void>) => Promise<void>
}

export interface RecordedAction {
    action: ReduxAction
    beforeState: Record<string, any>
    afterState: Record<string, any>
}

export interface PluginContext {
    recordedActions: RecordedAction[]
    pointerMap: Map<LogicWrapper | BuiltLogic, number>
    ranActions: Map<LogicWrapper | BuiltLogic, boolean>
}

export interface AsyncOperation {
    operation: string
    logic: BuiltLogic | LogicWrapper
    payload: any
}

export interface ExpectFunction<PayloadType> {
    common?(logic: BuiltLogic | LogicWrapper, actions: PayloadType): void
    sync?(logic: BuiltLogic | LogicWrapper, actions: PayloadType): void | AsyncOperation[]
    async?(logic: BuiltLogic | LogicWrapper, actions: PayloadType): Promise<void>
}
