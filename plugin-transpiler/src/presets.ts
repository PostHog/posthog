export const presets = {
    site: {
        envName: 'production',
        code: true,
        babelrc: false,
        configFile: false,
        filename: 'site.ts',
        presets: [['typescript', { isTSX: false, allExtensions: true }], 'env'],
        wrapper: (code: string): string => `(function () {let exports={};${code};return exports;})`,
    },
    frontend: {
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
        wrapper: (code: string): string =>
            `"use strict";\nexport function getFrontendApp (require) { let exports = {}; ${code}; return exports; }`,
    },
}
