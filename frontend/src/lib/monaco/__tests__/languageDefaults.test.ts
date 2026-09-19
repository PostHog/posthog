import * as monacoModule from 'monaco-editor'

import {
    _resetLanguageDefaultsForTests,
    applyJsonSchema,
    applyTypeScriptCompilerOptions,
} from 'lib/monaco/languageDefaults'

jest.mock('monaco-editor', () => ({
    typescript: {
        JsxEmit: { Preserve: 1, React: 2 },
        typescriptDefaults: {
            getCompilerOptions: () => ({ allowNonTsExtensions: true, target: 99 }),
            setCompilerOptions: jest.fn(),
        },
    },
    json: {
        jsonDefaults: {
            diagnosticsOptions: { trailingCommas: 'error' },
            setDiagnosticsOptions: jest.fn(),
        },
    },
}))

const setCompilerOptions = monacoModule.typescript.typescriptDefaults.setCompilerOptions as jest.Mock
const setDiagnosticsOptions = monacoModule.json.jsonDefaults.setDiagnosticsOptions as jest.Mock

describe('monaco language defaults', () => {
    beforeEach(() => {
        _resetLanguageDefaultsForTests()
        setCompilerOptions.mockClear()
        setDiagnosticsOptions.mockClear()
    })

    it("keeps monaco's own compiler options, which the language service needs for inmemory:// models", () => {
        applyTypeScriptCompilerOptions(monacoModule.typescript.JsxEmit.Preserve)

        expect(setCompilerOptions).toHaveBeenCalledWith({
            allowNonTsExtensions: true,
            target: 99,
            jsx: monacoModule.typescript.JsxEmit.Preserve,
            esModuleInterop: true,
        })
    })

    it('writes the TypeScript compiler options once while the value stays the same', () => {
        applyTypeScriptCompilerOptions(monacoModule.typescript.JsxEmit.Preserve)
        applyTypeScriptCompilerOptions(monacoModule.typescript.JsxEmit.Preserve)

        expect(setCompilerOptions).toHaveBeenCalledTimes(1)

        applyTypeScriptCompilerOptions(monacoModule.typescript.JsxEmit.React)

        expect(setCompilerOptions).toHaveBeenCalledTimes(2)
    })

    it('writes the JSON diagnostics options once while the schema stays the same', () => {
        const schema = { type: 'object' }

        applyJsonSchema(null)
        applyJsonSchema(null)

        expect(setDiagnosticsOptions).toHaveBeenCalledTimes(1)
        expect(setDiagnosticsOptions).toHaveBeenCalledWith({
            trailingCommas: 'error',
            validate: true,
            schemas: [],
        })

        applyJsonSchema(schema)
        applyJsonSchema(schema)

        expect(setDiagnosticsOptions).toHaveBeenCalledTimes(2)
        expect(setDiagnosticsOptions).toHaveBeenLastCalledWith({
            trailingCommas: 'error',
            validate: true,
            schemas: [{ uri: 'http://internal/node-schema.json', fileMatch: ['*'], schema }],
        })
    })
})
