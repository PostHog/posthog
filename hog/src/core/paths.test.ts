import { describe, expect, test } from 'bun:test'

import { hogDir } from './paths'

describe('hogDir', () => {
    test.each([
        ['macOS', 'darwin', {}, '/Users/ana/Library/Application Support/hog', false],
        ['macOS, run from source', 'darwin', {}, '/Users/ana/Library/Application Support/hog-dev', true],
        ['Linux', 'linux', {}, '/Users/ana/.config/hog', false],
        ['Linux with XDG_CONFIG_HOME', 'linux', { XDG_CONFIG_HOME: '/xdg' }, '/xdg/hog', false],
        ['Linux with a relative XDG_CONFIG_HOME', 'linux', { XDG_CONFIG_HOME: 'xdg' }, '/Users/ana/.config/hog', false],
        [
            'Windows',
            'win32',
            { APPDATA: 'C:\\Users\\ana\\AppData\\Roaming', LOCALAPPDATA: 'C:\\Users\\ana\\AppData\\Local' },
            'C:\\Users\\ana\\AppData\\Local\\hog',
            false,
        ],
    ] as const)('%s', (_name, platform, env, expected, isDevelopment) => {
        expect(hogDir({ platform, env, homeDir: () => '/Users/ana', isDevelopment })).toBe(expected)
    })
})
