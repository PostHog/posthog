import { PluginEvent } from '~/plugin-scaffold'

import { eventHasGroups, isFlagCalledPersonlessCandidate } from './flag-called-personless'

describe('flag-called-personless', () => {
    const enabledForAll = (): boolean => true
    const enabledForNone = (): boolean => false

    const event = (
        overrides: Partial<Pick<PluginEvent, 'event' | 'properties'>> = {}
    ): Pick<PluginEvent, 'event' | 'properties'> => ({
        event: '$feature_flag_called',
        properties: {},
        ...overrides,
    })

    describe('eventHasGroups', () => {
        it.each([
            [undefined, false],
            [{}, false],
            [{ $groups: {} }, false],
            [{ $groups: { org: 'acme' } }, true],
        ])('properties %j -> %s', (properties, expected) => {
            expect(eventHasGroups(properties as PluginEvent['properties'])).toBe(expected)
        })
    })

    describe('isFlagCalledPersonlessCandidate', () => {
        it('is a candidate for a flag-called event on an enabled team', () => {
            expect(isFlagCalledPersonlessCandidate(event(), 1, false, enabledForAll)).toBe(true)
        })

        it('is not a candidate for non-flag-called events', () => {
            expect(isFlagCalledPersonlessCandidate(event({ event: '$pageview' }), 1, false, enabledForAll)).toBe(false)
        })

        it('is not a candidate when person processing is explicitly true', () => {
            expect(isFlagCalledPersonlessCandidate(event(), 1, true, enabledForAll)).toBe(false)
        })

        it('is not a candidate when the event carries group keys', () => {
            expect(
                isFlagCalledPersonlessCandidate(
                    event({ properties: { $groups: { org: 'acme' } } }),
                    1,
                    false,
                    enabledForAll
                )
            ).toBe(false)
        })

        it('is not a candidate when the team is not enabled', () => {
            expect(isFlagCalledPersonlessCandidate(event(), 1, false, enabledForNone)).toBe(false)
        })
    })
})
