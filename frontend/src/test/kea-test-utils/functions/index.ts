import { toDispatchActions } from './toDispatchActions'
import { toMatchValues } from './toMatchValues'
import { printActions } from './printActions'
import { delay } from './delay'
import { ActionToDispatch } from '~/test/kea-test-utils'

export interface ExpectLogicMethods {
    then: (callback?: (value: any) => void | Promise<void>) => Promise<void>
    toDispatchActions: (actions: ActionToDispatch[]) => ExpectLogicMethods
    toMatchValues: (values: Record<string, any>) => ExpectLogicMethods
    printActions: (payload?: string) => ExpectLogicMethods
    delay: (ms: number) => ExpectLogicMethods
}

export const functions = {
    toDispatchActions,
    toMatchValues,
    printActions,
    delay,
}
