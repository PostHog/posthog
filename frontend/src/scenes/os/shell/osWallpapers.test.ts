import { resolveOsWallpaper } from './osWallpapers'

describe('resolveOsWallpaper', () => {
    test.each([
        ['a known wallpaper', 'hogzilla', 'hogzilla'],
        ['a wallpaper key that no longer exists', 'retired-wallpaper', 'keyboard-garden'],
        ['nothing saved yet', null, 'keyboard-garden'],
        ['a value of the wrong type', 42, 'keyboard-garden'],
    ])('resolves %s', (_description, stored, expected) => {
        expect(resolveOsWallpaper(stored).key).toBe(expected)
    })
})
