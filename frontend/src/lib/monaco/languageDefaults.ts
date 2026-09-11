import * as monacoModule from 'monaco-editor'

// Monaco holds one TypeScript and one JSON defaults object for the whole page, and a setter
// replaces the stored options rather than merging into them. Replacing the TypeScript options
// drops monaco's own `allowNonTsExtensions`, and without it the TypeScript program refuses the
// `inmemory://model/N` URI monaco gives an editor that has no path. Every language service call
// then answers "Could not find source file", for the rest of the page's life, so the editor has
// no hover, no autocomplete and no diagnostics. Merge into the current options instead, and
// write only a value that really changed, so a mount that changes nothing leaves the shared
// language worker alone.

let appliedJsx: monacoModule.typescript.JsxEmit | undefined

export function applyTypeScriptCompilerOptions(jsx: monacoModule.typescript.JsxEmit): void {
    if (appliedJsx === jsx) {
        return
    }
    appliedJsx = jsx
    const defaults = monacoModule.typescript.typescriptDefaults
    defaults.setCompilerOptions({ ...defaults.getCompilerOptions(), jsx, esModuleInterop: true })
}

let appliedJsonSchema: Record<string, any> | null | undefined

export function applyJsonSchema(schema: Record<string, any> | null): void {
    if (appliedJsonSchema === schema) {
        return
    }
    appliedJsonSchema = schema
    const defaults = monacoModule.json.jsonDefaults
    defaults.setDiagnosticsOptions({
        ...defaults.diagnosticsOptions,
        validate: true,
        schemas: schema
            ? [
                  {
                      uri: 'http://internal/node-schema.json',
                      fileMatch: ['*'],
                      schema: schema,
                  },
              ]
            : [],
    })
}

export function _resetLanguageDefaultsForTests(): void {
    appliedJsx = undefined
    appliedJsonSchema = undefined
}
