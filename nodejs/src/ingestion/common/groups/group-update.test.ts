import { Properties } from '~/plugin-scaffold'

import { calculateUpdate } from './group-update'

function permutations<T>(items: T[]): T[][] {
    if (items.length <= 1) {
        return [items]
    }
    return items.flatMap((item, i) =>
        permutations([...items.slice(0, i), ...items.slice(i + 1)]).map((rest) => [item, ...rest])
    )
}

function applyInOrder(updates: Properties[]): Properties {
    return updates.reduce<Properties>((current, update) => calculateUpdate(current, update).properties, {})
}

describe('calculateUpdate', () => {
    // Group property merging is the only piece of group ingestion that can observe event order.
    // These tests pin down exactly how much order matters: none for distinct keys, last-write-wins
    // for the same key. Nothing here depends on timestamps — see the comment in calculateUpdate.
    describe('ordering', () => {
        it('produces the same properties in every order when updates touch different keys', () => {
            const updates: Properties[] = [{ name: 'Acme' }, { plan: 'enterprise' }, { seats: 40 }]

            const results = permutations(updates).map(applyInOrder)

            expect(results).toHaveLength(6)
            for (const result of results) {
                expect(result).toEqual({ name: 'Acme', plan: 'enterprise', seats: 40 })
            }
        })

        it('is last-write-wins for the same key, and this is the only order-dependent behaviour', () => {
            expect(applyInOrder([{ plan: 'free' }, { plan: 'enterprise' }])).toEqual({ plan: 'enterprise' })
            expect(applyInOrder([{ plan: 'enterprise' }, { plan: 'free' }])).toEqual({ plan: 'free' })
        })

        it('never removes a key, so a partial update cannot undo an earlier one', () => {
            expect(applyInOrder([{ name: 'Acme', plan: 'free' }, { plan: 'enterprise' }])).toEqual({
                name: 'Acme',
                plan: 'enterprise',
            })
            expect(applyInOrder([{ name: 'Acme', plan: 'free' }, {}])).toEqual({ name: 'Acme', plan: 'free' })
        })

        it('is idempotent: replaying an update reports no change', () => {
            const first = calculateUpdate({}, { name: 'Acme' })
            const replay = calculateUpdate(first.properties, { name: 'Acme' })

            expect(first.updated).toBe(true)
            expect(replay.updated).toBe(false)
            expect(replay.properties).toEqual(first.properties)
        })
    })
})
