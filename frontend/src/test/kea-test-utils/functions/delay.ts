import { ExpectFunction } from '~/test/kea-test-utils'

export const delay: ExpectFunction<number> = {
    sync(logic, ms) {
        return [{ operation: 'delay', logic, payload: ms }]
    },

    async async(_, ms) {
        return new Promise((resolve) => setTimeout(resolve, ms))
    },
}
