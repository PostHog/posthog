import { dataOpsRedirectTarget } from './dataOpsRedirect'

describe('dataOpsRedirectTarget', () => {
    it.each([
        [{ tab: 'monitoring' }, '/warehouse/queries?tab=performance'],
        [{ tab: 'settings' }, '/warehouse/settings'],
        [{ tab: 'overview' }, '/warehouse/pipelines'],
        [{}, '/warehouse/pipelines'],
    ])('sends %j to %s', (searchParams, expected) => {
        expect(dataOpsRedirectTarget(searchParams)).toBe(expected)
    })
})
