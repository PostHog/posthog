import { transform } from '@babel/standalone'

export function transpileFrontend(rawCode: string): string {
    const { code } = transform(rawCode, {
        envName: 'production',
        code: true,
        babelrc: false,
        configFile: false,
        filename: 'frontend.tsx',
        plugins: ['transform-react-jsx'],
        presets: [
            ['typescript', { isTSX: true, allExtensions: true }],
            ['env', { targets: { esmodules: false } }],
        ],
    })
    if (!code) {
        throw new Error('Could not transpile frontend code')
    }
    return `"use strict";\nexport function getFrontendApp (require) { let exports = {}; ${code}; return exports; }`
}

export function transpileSite(rawCode: string): string {
    const { code } = transform(rawCode, {
        envName: 'production',
        code: true,
        babelrc: false,
        configFile: false,
        filename: 'site.ts',
        presets: [['typescript', { isTSX: false, allExtensions: true }], 'env'],
    })
    if (!code) {
        throw new Error('Could not transpile web code')
    }
    return `(function () {let exports={};${code};return exports;})`
}
