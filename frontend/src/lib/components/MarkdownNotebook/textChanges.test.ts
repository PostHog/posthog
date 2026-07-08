import {
    applyTextChanges,
    getTextChanges,
    invertTextChanges,
    mapTextIndex,
    transformTextChanges,
    tryApplyTextChanges,
} from './textChanges'

describe('textChanges', () => {
    describe('getTextChanges', () => {
        it.each([
            ['identical', 'hello', 'hello'],
            ['insertion', 'hello', 'hello world'],
            ['deletion', 'hello world', 'hello'],
            ['replacement', 'the quick brown fox', 'the slow brown fox'],
            ['multiple spans', 'one two three', 'ONE two THREE'],
            ['empty base', '', 'something'],
            ['empty next', 'something', ''],
            ['emoji', 'a 🦔 b', 'a 🦦 b'],
        ])('round-trips %s', (_name, baseText, nextText) => {
            expect(applyTextChanges(baseText, getTextChanges(baseText, nextText))).toEqual(nextText)
        })

        it('returns ascending non-overlapping spans accepted by tryApplyTextChanges', () => {
            const baseText = 'alpha beta gamma delta'
            const nextText = 'alpha BETA gamma DELTA epsilon'
            expect(tryApplyTextChanges(baseText, getTextChanges(baseText, nextText))).toEqual(nextText)
        })
    })

    describe('invertTextChanges', () => {
        it.each([
            ['insertion', 'hello', 'hello world'],
            ['deletion', 'hello world', 'hello'],
            ['replacement', 'the quick brown fox', 'the slow red fox'],
            ['multiple spans', 'one two three', 'ONE two THREE four'],
        ])('reverts %s', (_name, baseText, nextText) => {
            const changes = getTextChanges(baseText, nextText)
            expect(applyTextChanges(nextText, invertTextChanges(baseText, changes))).toEqual(baseText)
        })
    })

    describe('mapTextIndex', () => {
        const against = [
            { start: 2, end: 5, text: 'XYZAB' }, // replace 3 chars with 5
            { start: 8, end: 8, text: '!' }, // insertion
        ]

        it('shifts positions after a replacement by the length delta', () => {
            expect(mapTextIndex(6, against, 'left')).toEqual(8)
        })

        it('collapses positions inside a replaced span to its boundaries', () => {
            expect(mapTextIndex(3, against, 'left')).toEqual(2)
            expect(mapTextIndex(3, against, 'right')).toEqual(7)
        })

        it('breaks insertion ties by bias', () => {
            expect(mapTextIndex(8, against, 'left')).toEqual(10)
            expect(mapTextIndex(8, against, 'right')).toEqual(11)
        })
    })

    describe('transformTextChanges', () => {
        const merge = (baseText: string, localText: string, remoteText: string): string | null => {
            const localChanges = getTextChanges(baseText, localText)
            const remoteChanges = getTextChanges(baseText, remoteText)
            const rebased = transformTextChanges(localChanges, remoteChanges, 'against-first')
            return rebased === null ? null : applyTextChanges(applyTextChanges(baseText, remoteChanges), rebased)
        }

        it('merges non-overlapping edits from both sides', () => {
            expect(
                merge(
                    'Activation improved today.',
                    'Activation improved today after launch.',
                    'Activation clearly improved today.'
                )
            ).toEqual('Activation clearly improved today after launch.')
        })

        it('orders same-point insertions remote-first', () => {
            expect(merge('Hello world', 'Hello world Alice', 'Hello world Bob')).toEqual('Hello world Bob Alice')
        })

        it('never undoes a remote deletion via the old superset heuristic', () => {
            // Remote shortened the phrase; local appended elsewhere. The deletion must survive.
            expect(merge('the quick brown fox jumps', 'the quick brown fox jumps high', 'the fox jumps')).toEqual(
                'the fox jumps high'
            )
        })

        it('keeps a local insertion that lands inside a remotely rewritten span', () => {
            const result = merge('the quick fox', 'the quick little fox', 'the speedy fox')
            expect(result).toContain('speedy')
            expect(result).toContain('little')
        })

        it('splits a local deletion around a remote insertion instead of swallowing it', () => {
            // Local deletes "quick brown ", remote inserts "very " inside that range.
            expect(merge('the quick brown fox', 'the fox', 'the quick very brown fox')).toEqual('the very fox')
        })

        it('reports overlapping rewrites of the same words as a conflict', () => {
            expect(
                merge('Activation improved today.', 'Activation improved locally.', 'Activation improved remotely.')
            ).toBeNull()
        })

        it('converges for concurrent typing at different points', () => {
            const baseText = 'one two three'
            const localText = 'one 1 two three'
            const remoteText = 'one two three 3'
            const localChanges = getTextChanges(baseText, localText)
            const remoteChanges = getTextChanges(baseText, remoteText)

            const localOverRemote = transformTextChanges(localChanges, remoteChanges, 'against-first')
            const remoteOverLocal = transformTextChanges(remoteChanges, localChanges, 'changes-first')
            expect(localOverRemote).not.toBeNull()
            expect(remoteOverLocal).not.toBeNull()

            const viaRemoteFirst = applyTextChanges(applyTextChanges(baseText, remoteChanges), localOverRemote!)
            const viaLocalFirst = applyTextChanges(applyTextChanges(baseText, localChanges), remoteOverLocal!)
            expect(viaRemoteFirst).toEqual(viaLocalFirst)
        })

        it('converges for same-point insertions with consistent tie priorities', () => {
            const baseText = 'ab'
            const localChanges = [{ start: 1, end: 1, text: 'L' }]
            const remoteChanges = [{ start: 1, end: 1, text: 'R' }]

            const localOverRemote = transformTextChanges(localChanges, remoteChanges, 'against-first')!
            const remoteOverLocal = transformTextChanges(remoteChanges, localChanges, 'changes-first')!

            expect(applyTextChanges(applyTextChanges(baseText, remoteChanges), localOverRemote)).toEqual(
                applyTextChanges(applyTextChanges(baseText, localChanges), remoteOverLocal)
            )
        })
    })
})
