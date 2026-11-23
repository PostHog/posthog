import { describe, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { confinedWritePath, hogDir } from './paths'
import { processRuntime } from './runtime'

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

describe('confinedWritePath', () => {
    const base = realpathSync(mkdtempSync(join(tmpdir(), 'hog-paths-')))
    const project = join(base, 'project')
    mkdirSync(project)
    writeFileSync(join(base, 'outside.txt'), 'keep')
    writeFileSync(join(project, 'real.yaml'), '')
    symlinkSync(join(base, 'outside.txt'), join(project, 'out.yaml'))
    symlinkSync(join(base, 'missing.txt'), join(project, 'dangling.yaml'))
    symlinkSync(join(project, 'real.yaml'), join(project, 'in.yaml'))
    symlinkSync(base, join(project, 'up'))

    test.each([
        ['a new file', 'new.yaml', 'new.yaml'],
        ['a file in a folder that does not exist yet', 'a/b/new.yaml', 'a/b/new.yaml'],
        ['a link inside the folder', 'in.yaml', 'real.yaml'],
        ['an absolute path outside the folder', join(base, 'outside.txt'), undefined],
        ['a path that climbs out with ..', '../outside.txt', undefined],
        ['a link out of the folder', 'out.yaml', undefined],
        ['a link to a missing file', 'dangling.yaml', undefined],
        ['a file under a linked folder outside', 'up/new.yaml', undefined],
    ])('%s', async (_name, path, expected) => {
        const target = await confinedWritePath(processRuntime(), project, resolve(project, path))

        expect(target).toBe(expected === undefined ? undefined : join(project, expected))
    })
})
