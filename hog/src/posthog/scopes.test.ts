import { describe, expect, test } from 'bun:test'

import { scopesNotCovered } from './scopes'

describe('scopesNotCovered', () => {
    test.each([
        ['write grants read', ['insight:write'], ['insight:read'], []],
        ['a legacy scope grants the scope split off it', ['task:read'], ['inbox:read'], []],
    ])('%s', (_name, held, wanted, missing) => {
        expect(scopesNotCovered(held, wanted)).toEqual(missing)
    })
})
