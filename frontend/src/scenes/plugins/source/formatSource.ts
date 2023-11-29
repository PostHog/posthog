export async function formatSource(filename: string, source: string): Promise<string> {
    // Lazy-load prettier, as it's pretty big and its only use is formatting app source code
    // @ts-expect-error
    const prettier = (await import('prettier/standalone')).default
    // @ts-expect-error
    const parserTypeScript = (await import('prettier/parser-typescript')).default

    if (filename.endsWith('.json')) {
        return JSON.stringify(JSON.parse(source), null, 4) + '\n'
    }

    return prettier.format(source, {
        filepath: filename,
        parser: 'typescript',
        plugins: [parserTypeScript],
        // copied from .prettierrc
        semi: false,
        trailingComma: 'es5',
        singleQuote: true,
        tabWidth: 4,
        printWidth: 120,
    })
}
