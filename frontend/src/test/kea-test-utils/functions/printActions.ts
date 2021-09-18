import { ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'

export const printActions: ExpectFunction<any> = {
    common(logic, payload) {
        const { recordedActions, pointerMap } = testUtilsContext()
        const logicPointer = pointerMap.get(logic)

        console.log(`💈 Logging actions for logic "${logic.pathString}": ${payload ?? ''}`)

        recordedActions.forEach(({ action }, index) => {
            console.log(`💥 ${index}. ${logicPointer === index ? ' ⬅️ POINTER' : ''}${JSON.stringify(action, null, 2)}`)
        })
    },
}
