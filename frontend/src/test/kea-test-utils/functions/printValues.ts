import { ExpectFunction } from '~/test/kea-test-utils'

export const printValues: ExpectFunction<any> = {
    common(logic) {
        console.log(`💈 Logging values for logic "${logic.pathString}": ${JSON.stringify(logic.values, null, 2)}`)
    },
}
