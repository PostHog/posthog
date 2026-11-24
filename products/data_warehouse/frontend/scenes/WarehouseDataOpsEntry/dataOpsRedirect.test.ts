import { dataOpsRedirectTarget } from './dataOpsRedirect'

describe('dataOpsRedirectTarget', () => {
    it.each([
        [{ tab: 'monitoring' }, '/warehouse/queries?tab=performance'],
        [{ tab: 'settings' }, '/warehouse/settings'],
        [{ tab: 'overview' }, '/warehouse/storage?tab=readiness'],
        [{}, '/warehouse/storage?tab=readiness'],
    ])('sends %j to %s', (searchParams, expected) => {
        expect(dataOpsRedirectTarget(searchParams)).toBe(expected)
    })
})
