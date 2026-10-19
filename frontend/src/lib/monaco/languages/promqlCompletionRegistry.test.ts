import {
    type PromQLCompletionProvider,
    getPromQLCompletionProvider,
    setPromQLCompletionProvider,
} from './promqlCompletionRegistry'

describe('promqlCompletionRegistry', () => {
    it('gives the older editor its suggestions back when the newer one closes', () => {
        const older: PromQLCompletionProvider = async () => null
        const newer: PromQLCompletionProvider = async () => null
        const removeOlder = setPromQLCompletionProvider(older)
        const removeNewer = setPromQLCompletionProvider(newer)
        expect(getPromQLCompletionProvider()).toBe(newer)

        removeNewer()
        expect(getPromQLCompletionProvider()).toBe(older)

        removeOlder()
        expect(getPromQLCompletionProvider()).toBeNull()
    })
})
