import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

/**
 * Builds @posthog/quill-charts for npm. Charts is pure JS/canvas — no CSS
 * pipeline. The runtime deps (d3-*, dayjs, @floating-ui/react,
 * simple-statistics) stay external and are redeclared as real
 * `dependencies` so the consumer's package manager installs them; react /
 * react-dom are peers. `testing` ships as a second entry so code outside
 * this repo can test its charts; @testing-library/react is an optional peer.
 * story-helpers stays unpublished — only this repo's stories use it.
 */
export default defineConfig({
    plugins: [
        react(),
        dts({
            tsconfigPath: resolve(__dirname, 'tsconfig.build.json'),
            exclude: [
                'src/**/*.test.ts',
                'src/**/*.test.tsx',
                'src/**/*.stories.ts',
                'src/**/*.stories.tsx',
                'src/story-helpers.tsx',
            ],
        }),
    ],
    build: {
        lib: {
            entry: {
                index: resolve(__dirname, 'src/index.ts'),
                testing: resolve(__dirname, 'src/testing/index.ts'),
            },
            formats: ['es', 'cjs'],
            fileName: (format, entryName) => `${entryName}.${format === 'es' ? 'js' : 'cjs'}`,
        },
        rollupOptions: {
            external: [
                'react',
                'react-dom',
                'react/jsx-runtime',
                '@floating-ui/react',
                '@testing-library/react',
                'd3-array',
                'd3-color',
                'd3-scale',
                'd3-shape',
                'dayjs',
                /^dayjs\//,
                'simple-statistics',
            ],
        },
    },
})
