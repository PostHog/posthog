import fs from 'fs'
import path from 'path'

describe('monacoStylesheet.css', () => {
    it('imports every stylesheet the installed monaco-editor ships', () => {
        const monacoEsm = path
            .dirname(require.resolve('monaco-editor/esm/vs/editor/editor.api.js'))
            .replace(/[\\/]vs[\\/]editor$/, '')
        const shipped = fs
            .readdirSync(monacoEsm, { recursive: true, encoding: 'utf8' })
            .filter((file) => file.endsWith('.css'))
            .map((file) => `monaco-editor/esm/${file.split(path.sep).join('/')}`)
            .sort()

        const imported = fs
            .readFileSync(path.join(__dirname, 'monacoStylesheet.css'), 'utf8')
            .match(/@import '([^']+)'/g)!
            .map((line) => line.slice("@import '".length, -1))

        expect(imported).toEqual(shipped)
    })
})
