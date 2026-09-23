import { OsAppIconApp, osAppIconColor } from './OsAppIcon'

describe('osAppIconColor', () => {
    it.each<[string, OsAppIconApp | null, string | null]>([
        [
            'the light color of a manifest override',
            { iconType: 'dashboard', iconColor: ['var(--color-product-surveys-light)', 'var(--x)'] },
            'var(--color-product-surveys-light)',
        ],
        ['the color of the icon type', { iconType: 'session_replay' }, 'var(--color-product-session-replay-light)'],
        ['no color for an icon type without one, so the tile turns graphite', { iconType: 'settings' }, null],
        ['no color for an OS item that is not an app', null, null],
    ])('gives %s', (_, app, expected) => {
        expect(osAppIconColor(app)).toEqual(expected)
    })
})
