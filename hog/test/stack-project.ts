import { mkdirSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

export function installStackPackages(root: string, compiler = true): void {
    const modules = join(root, 'node_modules')
    mkdirSync(join(modules, '@posthog'), { recursive: true })
    const sdk = realpathSync(dirname(require.resolve('@posthog/sdk/package.json')))
    symlinkSync(sdk, join(modules, '@posthog/sdk'), 'junction')
    if (compiler) {
        const typescript = realpathSync(dirname(require.resolve('typescript/package.json')))
        symlinkSync(typescript, join(modules, 'typescript'), 'junction')
    }
    writeFileSync(join(root, 'package.json'), JSON.stringify({ private: true, type: 'module' }))
    const compilerOptions = {
        target: 'ES2022',
        module: 'ESNext',
        moduleResolution: 'bundler',
        strict: true,
        skipLibCheck: true,
        types: [],
        noEmit: true,
    }
    writeFileSync(join(root, 'tsconfig.json'), JSON.stringify({ compilerOptions }))
}
