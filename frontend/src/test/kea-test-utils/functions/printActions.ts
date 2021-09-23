import { ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'

export const printActions: ExpectFunction<any> = {
    common(logic, payload) {
        const { recordedHistory, historyIndex } = testUtilsContext()

        console.log(`💈 Logging actions for logic "${logic.pathString}": ${payload ?? ''}`)

        recordedHistory.forEach(({ action }, index) => {
            console.log(`💥 ${index}. ${historyIndex === index ? ' ⬅️ POINTER' : ''}${JSON.stringify(action, null, 2)}`)
        })
    },
}
