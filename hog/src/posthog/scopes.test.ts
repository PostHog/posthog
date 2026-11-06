import { describe, expect, test } from 'bun:test'

import { scopesNotCovered } from './scopes'

describe('scopesNotCovered', () => {
    test.each([
        ['write grants read', ['insight:write'], ['insight:read'], []],
        ['a legacy scope grants the scope split off it', ['task:read'], ['inbox:read'], []],
        ['asking for write leaves out the read it grants', [], ['endpoint:read', 'endpoint:write'], ['endpoint:write']],
    ])('%s', (_name, held, wanted, missing) => {
        expect(scopesNotCovered(held, wanted)).toEqual(missing)
    })
})
