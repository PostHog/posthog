import { ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'
import { getContext } from 'kea'

export const toMatchValues: ExpectFunction<Record<string, any>> = {
    common(logic, values) {
        const { recordedHistory, ranActions, historyIndex } = testUtilsContext()
        const currentState = ranActions
            ? recordedHistory[historyIndex || 0]?.afterState || getContext().store.getState()
            : getContext().store.getState()
        for (const [key, value] of Object.entries(values)) {
            if (!(key in logic.selectors)) {
                throw new Error(`Count not find value with key "${key}" in logic "${logic.pathString}"`)
            }
            const currentValue = logic.selectors[key](currentState, logic.props)
            expect(currentValue).toEqual(value)
        }
    },
}
