import { toDispatchActions } from './toDispatchActions'
import { toDispatchActionsInAnyOrder } from './toDispatchActionsInAnyOrder'
import { toFinishAllListeners } from './toFinishAllListeners'
import { toFinishListeners } from './toFinishListeners'
import { toMatchValues } from './toMatchValues'
import { toMount } from './toMount'
import { printActions, PrintActionsOptions } from './printActions'
import { delay } from './delay'
import { ActionToDispatch, ExpectFunction } from '~/test/kea-test-utils'
import { BuiltLogic, LogicWrapper } from 'kea'

export interface ExpectLogicMethods {
    then: (callback?: (value: any) => void | Promise<void>) => Promise<void>
    toDispatchActions: ((actions: ActionToDispatch[]) => ExpectLogicMethods) &
        ((logic: BuiltLogic | LogicWrapper, actions: ActionToDispatch[]) => ExpectLogicMethods)
    toDispatchActionsInAnyOrder: ((actions: ActionToDispatch[]) => ExpectLogicMethods) &
        ((logic: BuiltLogic | LogicWrapper, actions: ActionToDispatch[]) => ExpectLogicMethods)
    toFinishListeners: ((ms?: number) => ExpectLogicMethods) &
        ((logic: BuiltLogic | LogicWrapper, ms?: number) => ExpectLogicMethods)
    toFinishAllListeners: (ms?: number) => ExpectLogicMethods
    toMatchValues: ((values: Record<string, any>) => ExpectLogicMethods) &
        ((logic: BuiltLogic | LogicWrapper, values: Record<string, any>) => ExpectLogicMethods)
    toMount: (otherLogics?: BuiltLogic | LogicWrapper | (BuiltLogic | LogicWrapper)[]) => ExpectLogicMethods
    printActions: (options?: PrintActionsOptions) => ExpectLogicMethods
    delay: (ms: number) => ExpectLogicMethods
}

export const functions: Record<string, ExpectFunction<any>> = {
    toDispatchActions,
    toDispatchActionsInAnyOrder,
    toFinishAllListeners,
    toFinishListeners,
    toMatchValues,
    toMount,
    printActions,
    delay,
}
