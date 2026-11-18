import { describe, expect, test } from 'bun:test'

import { compareVersions } from './api-catalog'

describe('compareVersions', () => {
    test.each([
        ['1.0.0-alpha.0', '1.0.0-alpha.-', -1],
        ['1.0.0-alpha.9', '1.0.0-alpha.10', -1],
        ['1.0.0-alpha', '1.0.0-alpha.1', -1],
        ['1.0.0-Beta', '1.0.0-alpha', -1],
        ['1.0.0-rc.1', '1.0.0', -1],
        ['1.2.0', '1.10.0', -1],
        ['1.0.0+build.5', '1.0.0', 0],
        ['1.0.0-alpha..0', '1.0.0', undefined],
        ['1.0.0-alpha.01', '1.0.0', undefined],
        ['01.0.0', '1.0.0', undefined],
    ])('orders %s against %s', (a, b, expected) => {
        expect(compareVersions(a, b)).toBe(expected)
    })
})
