import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

/**
 * Builds @posthog/quill-charts for npm. Charts is pure JS/canvas — no CSS
 * pipeline. The runtime deps (d3-*, dayjs, @floating-ui/react,
 * simple-statistics) stay external and are redeclared as real
 * `dependencies` so the consumer's package manager installs them; react /
 * react-dom are peers. The dev/story-only entries (testing, story-helpers)
 * are excluded — in-repo consumers reach them via tsconfig path aliases /
 * jest moduleNameMapper against src, not the published package.
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
                'src/testing/**',
                'src/story-helpers.tsx',
            ],
        }),
    ],
    build: {
        lib: {
            entry: resolve(__dirname, 'src/index.ts'),
            formats: ['es', 'cjs'],
            fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
        },
        rollupOptions: {
            external: [
                'react',
                'react-dom',
                'react/jsx-runtime',
                '@floating-ui/react',
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
