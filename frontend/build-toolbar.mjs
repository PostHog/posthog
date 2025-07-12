#!/usr/bin/env node
import { build } from 'vite'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

// Build toolbar with special configuration
await build({
    configFile: false,
    root: __dirname,
    build: {
        outDir: 'dist',
        rollupOptions: {
            input: resolve(__dirname, 'src/toolbar/index.tsx'),
            output: {
                file: resolve(__dirname, 'dist/toolbar.js'),
                format: 'iife',
                name: 'posthogToolbar',
                // Add the same banner/footer as esbuild
                banner: 'var posthogToolbar = (function () { var define = undefined;',
                footer: 'return posthogToolbar })();',
            },
        },
        sourcemap: true,
    },
    plugins: [
        // Import the toolbar plugin
        (await import('./vite-toolbar-plugin.js')).toolbarDenylistPlugin(),
    ],
    define: {
        global: 'globalThis',
        'process.env.NODE_ENV': '"production"',
    },
    resolve: {
        alias: {
            '~': resolve(__dirname, 'src'),
            '@': resolve(__dirname, 'src'),
        },
    },
})

/* eslint-disable-next-line no-console */
console.log('✅ Toolbar built successfully')
