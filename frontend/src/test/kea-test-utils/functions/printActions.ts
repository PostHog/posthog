import { ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'

export const printActions: ExpectFunction<any> = {
    common(logic, payload) {
        const { recordedActions, pointerMap } = testUtilsContext()

        console.log(`💈 Logging actions for logic "${logic.pathString}": ${payload ?? ''}`)

        recordedActions.forEach(({ action }, index) => {
            console.log(`💥 ${index}. ${pointerMap === index ? ' ⬅️ POINTER' : ''}${JSON.stringify(action, null, 2)}`)
        })
    },
}
