import { parseRefreshTeams } from './config'

describe('parseRefreshTeams', () => {
    it('accepts only the same all-digit team ids as the Django refresh partition', () => {
        expect(parseRefreshTeams('1, 2x, -3, 4')).toEqual(new Set([1, 4]))
    })
})
