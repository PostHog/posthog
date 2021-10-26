// @ts-ignore
import { ExpectFunction } from '~/test/kea-test-utils'

export const printValues: ExpectFunction<any> = {
    // @ts-ignore
    common(logic) {
        console.log(`💈 Logging values for logic "${logic.pathString}": ${JSON.stringify(logic.values, null, 2)}`)
    },
}
