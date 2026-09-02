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
    // Property merging is the only piece of group ingestion that can observe event order.
    // These pin down how much: none for distinct keys, last-write-wins for the same key.
    describe('ordering', () => {
        it('produces the same properties in every order when updates touch different keys', () => {
            const updates: Properties[] = [{ name: 'Acme' }, { plan: 'enterprise' }, { seats: 40 }]

            const results = permutations(updates).map(applyInOrder)

            expect(results).toHaveLength(6)
            for (const result of results) {
                expect(result).toEqual({ name: 'Acme', plan: 'enterprise', seats: 40 })
            }
        })

        it('is last-write-wins for the same key, and this is the only order-dependent behavior', () => {
            expect(applyInOrder([{ plan: 'free' }, { plan: 'enterprise' }])).toEqual({ plan: 'enterprise' })
            expect(applyInOrder([{ plan: 'enterprise' }, { plan: 'free' }])).toEqual({ plan: 'free' })
        })
    })
})
