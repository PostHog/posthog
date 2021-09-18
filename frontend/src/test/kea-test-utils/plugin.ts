import { getPluginContext, KeaPlugin, setPluginContext } from 'kea'
import { Action as ReduxAction } from 'redux'
import { PluginContext } from '~/test/kea-test-utils/types'

export function testUtilsContext(): PluginContext {
    return getPluginContext('testUtils') as PluginContext
}

export function resetTestUtilsContext(): void {
    setPluginContext('testUtils', {
        recordedActions: [],
        pointerMap: new Map(),
        ranActions: new Map(),
    } as PluginContext)
}

export const testUtilsPlugin: () => KeaPlugin = () => ({
    name: 'testUtils',

    events: {
        afterPlugin() {
            resetTestUtilsContext()
        },

        beforeReduxStore(options) {
            options.middleware.push((store) => (next) => (action: ReduxAction) => {
                const beforeState = store.getState()
                const response = next(action)
                const afterState = store.getState()

                const { recordedActions } = testUtilsContext()
                recordedActions.push({
                    action,
                    beforeState,
                    afterState,
                })

                return response
            })
        },

        beforeCloseContext() {
            resetTestUtilsContext()
        },
    },
})
