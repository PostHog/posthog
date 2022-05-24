import * as prettier from 'prettier/standalone'
import * as parserTypeScript from 'prettier/parser-typescript'
export function formatSource(filename: string, source: string): string {
    if (filename.endsWith('.json')) {
        return JSON.stringify(JSON.parse(source), null, 4) + '\n'
    }

    return prettier.format(source, {
        filepath: filename,
        parser: 'typescript',
        plugins: [parserTypeScript],
        // coped from .prettierrc
        semi: false,
        trailingComma: 'es5',
        singleQuote: true,
        tabWidth: 4,
        printWidth: 120,
    })
}
