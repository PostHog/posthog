import { Action as ReduxAction } from 'redux'
import { BuiltLogic, LogicWrapper } from 'kea'

export interface Action extends ReduxAction {
    payload: Record<string, any>
}

export type ActionToDispatch = string | Action | ((action: Action) => boolean)

export interface RecordedAction {
    action: Action
    beforeState: Record<string, any>
    afterState: Record<string, any>
}

export interface PluginContext {
    recordedHistory: RecordedAction[]
    historyIndex: number
    ranActions: boolean
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
