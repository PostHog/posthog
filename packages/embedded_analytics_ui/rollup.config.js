import typescript from 'rollup-plugin-typescript2'
import postcss from 'rollup-plugin-postcss'
import { nodeResolve } from '@rollup/plugin-node-resolve'
import commonjs from '@rollup/plugin-commonjs'
import tailwindcss from 'tailwindcss'
import autoprefixer from 'autoprefixer'

export default {
    input: 'src/index.ts',
    output: [
        {
            file: 'dist/index.cjs.js',
            format: 'cjs',
            sourcemap: true,
        },
        {
            file: 'dist/index.esm.js',
            format: 'esm',
            sourcemap: true,
        },
    ],
    plugins: [
        nodeResolve({
            browser: true,
            preferBuiltins: false,
        }),
        commonjs(),
        postcss({
            extract: true,
            minimize: true,
            sourceMap: true,
            plugins: [tailwindcss, autoprefixer],
        }),
        typescript({
            clean: true,
            tsconfig: 'tsconfig.json',
        }),
    ],
    external: ['react', 'react-dom'],
    onwarn(warning, warn) {
        // Suppress circular dependency warnings from third-party libraries
        if (warning.code === 'CIRCULAR_DEPENDENCY') {
            const message = warning.message || warning.toString()
            if (message.includes('d3-interpolate') || message.includes('recharts')) {
                return // Don't show these warnings
            }
        }

        // Suppress "use client" directive warnings from Radix UI
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE') {
            const message = warning.message || warning.toString()
            if (message.includes('@radix-ui')) {
                return // Don't show these warnings
            }
        }

        // Show all other warnings
        warn(warning)
    },
}
