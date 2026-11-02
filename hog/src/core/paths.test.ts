import { describe, expect, test } from 'bun:test'

import { hogDir } from './paths'

describe('hogDir', () => {
    test.each([
        ['macOS', 'darwin', {}, '/Users/ana/Library/Application Support/hog'],
        ['Linux', 'linux', {}, '/Users/ana/.config/hog'],
        ['Linux with XDG_CONFIG_HOME', 'linux', { XDG_CONFIG_HOME: '/xdg' }, '/xdg/hog'],
        ['Linux with a relative XDG_CONFIG_HOME', 'linux', { XDG_CONFIG_HOME: 'xdg' }, '/Users/ana/.config/hog'],
        ['Windows', 'win32', { APPDATA: 'C:\\Users\\ana\\AppData\\Roaming' }, 'C:\\Users\\ana\\AppData\\Roaming\\hog'],
    ] as const)('%s', (_name, platform, env, expected) => {
        expect(hogDir({ platform, env, homeDir: () => '/Users/ana' })).toBe(expected)
    })
})
