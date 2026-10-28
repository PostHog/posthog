import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { isWelcomeNavItemShown } from './welcomeNavItem'

describe('isWelcomeNavItemShown', () => {
    const now = dayjs('2026-10-15T12:00:00Z')
    const flagsReading = (variant: string): { flags: Record<string, string>; reads: string[] } => {
        const reads: string[] = []
        const flags = new Proxy({ [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: variant } as Record<string, string>, {
            get: (target, key: string) => {
                reads.push(key)
                return target[key]
            },
        })
        return { flags, reads }
    }

    it.each([
        ['a 6 day old project on the test arm', '2026-10-09T13:00:00Z', 'test', true],
        ['a 7 day old project on the test arm', '2026-10-08T12:00:00Z', 'test', false],
        ['a new project on the control arm', '2026-10-14T12:00:00Z', 'control', false],
        ['a team with no creation date', undefined, 'test', false],
    ])('%s', (_name, createdAt, variant, expected) => {
        expect(isWelcomeNavItemShown(createdAt, flagsReading(variant).flags, now)).toBe(expected)
    })

    it('does not read the experiment flag for an old project, so it records no exposure', () => {
        const { flags, reads } = flagsReading('test')
        isWelcomeNavItemShown('2026-01-01T00:00:00Z', flags, now)
        expect(reads).toEqual([])
    })
})
