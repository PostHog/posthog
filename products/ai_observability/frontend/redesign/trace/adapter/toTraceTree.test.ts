import { makeEvent } from './testFixtures'
import { isErrorEvent } from './toTraceTree'

describe('toTraceTree', () => {
    describe('isErrorEvent', () => {
        it.each([
            ['a populated $ai_error with no flag', { $ai_error: 'boom' }, true],
            ['$ai_is_error: true with no error payload', { $ai_is_error: true }, true],
            ['$ai_is_error: "true" (SDK-serialized boolean)', { $ai_is_error: 'true' }, true],
            ['neither an error payload nor a truthy flag', { $ai_is_error: false }, false],
        ])('%s -> %s', (_description, properties, expected) => {
            expect(isErrorEvent(makeEvent({ id: 'e1', properties }))).toBe(expected)
        })
    })
})
