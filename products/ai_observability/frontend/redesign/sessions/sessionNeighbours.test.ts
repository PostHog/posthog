import { sessionNeighbours } from './sessionNeighbours'
import { makeSessionListItem } from './testFixtures'

const items = ['a', 'b', 'c'].map((id) => makeSessionListItem({ id }))

describe('sessionNeighbours', () => {
    test.each([
        ['the first row', 'a', [null, 'b']],
        ['a middle row', 'b', ['a', 'c']],
        ['the last row', 'c', ['b', null]],
    ])('steps from %s to the rows beside it', (_name, openId, [previous, next]) => {
        const neighbours = sessionNeighbours(items, openId)

        expect([neighbours?.previous?.id ?? null, neighbours?.next?.id ?? null]).toEqual([previous, next])
    })

    test.each([
        ['a session the rows do not show', 'z'],
        ['no open session', null],
    ])('has no neighbours for %s', (_name, openId) => {
        expect(sessionNeighbours(items, openId)).toBeNull()
    })
})
