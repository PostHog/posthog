import * as prettier from 'prettier/standalone'
import * as parserTypeScript from 'prettier/parser-typescript'
export function formatSource(filename: string, source: string): string {
    return prettier.format(source, {
        filepath: filename,
        parser: 'typescript',
        plugins: [parserTypeScript],
        semi: false,
        tabWidth: 4,
    })
}
