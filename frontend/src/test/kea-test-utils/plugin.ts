import { getPluginContext, KeaPlugin, setPluginContext } from 'kea'
import { Action, PluginContext } from '~/test/kea-test-utils/types'

export function testUtilsContext(): PluginContext {
    return getPluginContext('testUtils') as PluginContext
}

export function resetTestUtilsContext(): void {
    setPluginContext('testUtils', {
        recordedHistory: [],
        historyIndex: 0,
        ranActions: false,
    } as PluginContext)
}

export const testUtilsPlugin: () => KeaPlugin = () => ({
    name: 'testUtils',

    events: {
        afterPlugin() {
            resetTestUtilsContext()
        },

        beforeReduxStore(options) {
            options.middleware.push((store) => (next) => (action: Action) => {
                const beforeState = store.getState()
                const response = next(action)
                const afterState = store.getState()

                const { recordedHistory } = testUtilsContext()
                recordedHistory.push({
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
