import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { removeUnlinkedStylesheets } from './unlinkedStylesheets.mjs'

describe('removeUnlinkedStylesheets', () => {
    let dir: string
    const write = (file: string): void => fs.writeFileSync(path.join(dir, file), 'x')
    const exists = (file: string): boolean => fs.existsSync(path.join(dir, file))

    beforeEach(() => {
        dir = fs.mkdtempSync(path.join(os.tmpdir(), 'unlinked-stylesheets-'))
        fs.mkdirSync(path.join(dir, 'dist'))
    })
    afterEach(() => fs.rmSync(dir, { recursive: true, force: true }))

    it('keeps linked stylesheets when builds complete in either order', () => {
        for (const file of ['index-A.css', 'index-A.css.map', 'Scene-B.css', 'Scene-B.css.map', 'exporter-C.css']) {
            write(`dist/${file}`)
        }
        const app = {
            'dist/index-A.js': { entryPoint: 'src/index.tsx', cssBundle: 'dist/index-A.css' },
            'dist/index-A.css': { bytes: 10 },
            'dist/Scene-B.css': { bytes: 5 },
        }
        const exporter = {
            'dist/exporter-C.js': { entryPoint: 'src/exporter/index.tsx', cssBundle: 'dist/exporter-C.css' },
            'dist/exporter-C.css': { bytes: 1 },
            'dist/index-A.css': { bytes: 10 },
        }

        removeUnlinkedStylesheets(dir, exporter, 'src/exporter/index.tsx')
        removeUnlinkedStylesheets(dir, app, 'src/index.tsx')

        expect(['index-A.css', 'index-A.css.map', 'exporter-C.css'].every((f) => exists(`dist/${f}`))).toBe(true)
        expect(exists('dist/Scene-B.css') || exists('dist/Scene-B.css.map')).toBe(false)
    })

    it('removes nothing when the entry has no linked stylesheet', () => {
        write('dist/Scene-B.css')
        expect(() => removeUnlinkedStylesheets(dir, { 'dist/Scene-B.css': { bytes: 5 } }, 'src/index.tsx')).toThrow(
            'No linked stylesheet found for src/index.tsx'
        )
        expect(exists('dist/Scene-B.css')).toBe(true)
    })
})
