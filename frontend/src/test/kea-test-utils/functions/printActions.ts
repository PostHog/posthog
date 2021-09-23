import { ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'

export interface PrintActionsOptions {
    compact?: boolean
}

export const printActions: ExpectFunction<any> = {
    common(logic, options: PrintActionsOptions) {
        const { recordedHistory, historyIndex } = testUtilsContext()

        const text = recordedHistory
            .map(({ action }, index) => {
                const icon = historyIndex === index ? '👉' : action.type.includes(`(${logic.pathString})`) ? '🥦' : '🐠'
                return options.compact
                    ? `${icon} ${index}. ${action.type}${action.payload ? ' - ' + JSON.stringify(action.payload) : ''}`
                    : `${icon} ${index}. ${JSON.stringify(action, null, 2)}`
            })
            .join('\n')

        console.log(`💈 Logging actions for logic "${logic.pathString}": \n${text}`)
    },
}
