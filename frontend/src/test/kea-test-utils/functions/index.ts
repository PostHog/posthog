import { toDispatchActions } from './toDispatchActions'
import { toFinishAllListeners } from './toFinishAllListeners'
import { toFinishListeners } from './toFinishListeners'
import { toMatchValues } from './toMatchValues'
import { toMount } from './toMount'
import { printActions } from './printActions'
import { delay } from './delay'
import { ActionToDispatch, ExpectFunction } from '~/test/kea-test-utils'
import { BuiltLogic, LogicWrapper } from 'kea'

export interface ExpectLogicMethods {
    then: (callback?: (value: any) => void | Promise<void>) => Promise<void>
    toDispatchActions: (actions: ActionToDispatch[]) => ExpectLogicMethods
    toFinishListeners: (arg?: undefined) => ExpectLogicMethods
    toFinishAllListeners: (arg?: undefined) => ExpectLogicMethods
    toMatchValues: (values: Record<string, any>) => ExpectLogicMethods
    toMount: (otherLogics?: BuiltLogic | LogicWrapper | (BuiltLogic | LogicWrapper)[]) => ExpectLogicMethods
    printActions: (payload?: string) => ExpectLogicMethods
    delay: (ms: number) => ExpectLogicMethods
}

export const functions: Record<string, ExpectFunction<any>> = {
    toDispatchActions,
    toFinishAllListeners,
    toFinishListeners,
    toMatchValues,
    toMount,
    printActions,
    delay,
}
