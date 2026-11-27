import { firstSeenTooltip } from './firstSeenTooltip'

describe('firstSeenTooltip', () => {
    it('names the earliest date the read checked', () => {
        expect(firstSeenTooltip('2026-08-02')).toEqual(
            'Earliest activity since Aug 2, 2026. Nothing older was checked.'
        )
    })
})
