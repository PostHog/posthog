import { transform } from '@babel/standalone'

import { Hub } from '../../../types'
import { loopTimeout } from './loop-timeout'
import { promiseTimeout } from './promise-timeout'
import { replaceImports } from './replace-imports'

const memoize: Record<string, string> = {}

export function transformCode(
    rawCode: string,
    server: Hub,
    imports: Record<string, any>,
    usedImports: Set<string>
): string {
    if (process.env.NODE_ENV === 'test' && memoize[rawCode]) {
        // Memoizing in tests for speed, not in production though due to reliability concerns
        return memoize[rawCode]
    }

    const { code } = transform(rawCode, {
        envName: 'production',
        code: true,
        babelrc: false,
        configFile: false,
        filename: 'index.ts',
        presets: ['typescript', ['env', { targets: { node: process.versions.node } }]],
        plugins: [replaceImports(server, imports, usedImports), loopTimeout(server), promiseTimeout(server)],
    })
    if (!code) {
        throw new Error(`Babel transform gone wrong! Could not process the following code:\n${rawCode}`)
    }
    if (process.env.NODE_ENV === 'test') {
        memoize[rawCode] = code
    }
    return code
}
