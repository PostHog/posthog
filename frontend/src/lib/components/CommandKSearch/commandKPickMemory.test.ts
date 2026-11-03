import { PICK_MEMORY_LIMIT, PICKED_THRESHOLD, pickScores, recordPick } from './commandKPickMemory'

const DAY = 24 * 60 * 60 * 1000

describe('commandKPickMemory', () => {
    test.each([
        ['the same text', 'session replay', true],
        ['a shorter start of the picked text', 'sess', true],
        ['text that does not start the picked text', 'replay', false],
        ['longer text than the picked text', 'session replay settings', false],
    ])('a pick counts for %s', (_, typed, counts) => {
        const memory = recordPick([], 'session replay', 'product-Session replay', 0)

        expect(pickScores(memory, typed, 0).has('product-Session replay')).toBe(counts)
    })

    test.each([
        [1, true],
        [60, false],
    ])('a pick made %s days ago is still remembered: %s', (days, remembered) => {
        const memory = recordPick([], 'replay', 'product-Session replay', 0)

        const score = pickScores(memory, 'replay', days * DAY).get('product-Session replay') ?? 0

        expect(score >= PICKED_THRESHOLD).toBe(remembered)
    })

    it('keeps only the most recently used texts', () => {
        let memory = recordPick([], 'oldest', 'item-0', 0)
        for (let index = 1; index <= PICK_MEMORY_LIMIT; index++) {
            memory = recordPick(memory, `text ${index}`, `item-${index}`, index)
        }

        expect(memory).toHaveLength(PICK_MEMORY_LIMIT)
        expect(pickScores(memory, 'oldest', PICK_MEMORY_LIMIT).size).toBe(0)
    })
})
