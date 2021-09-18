import { Action as ReduxAction } from 'redux'
import { BuiltLogic, LogicWrapper } from 'kea'

export interface CallableMethods {
    toDispatchActions: (actions: (string | ReduxAction | ((action: ReduxAction) => boolean))[]) => CallableMethods
    toMatchValues: (values: Record<string, any>) => CallableMethods
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
}

export interface AsyncOperation {
    operation: 'toDispatchActions' | 'toMatchValues'
    logic: BuiltLogic | LogicWrapper
    payload: any
}
