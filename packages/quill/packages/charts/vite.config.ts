import react from '@vitejs/plugin-react'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'path'
import { defineConfig, type Plugin } from 'vite'
import dts from 'vite-plugin-dts'

/**
 * Builds @posthog/quill-charts for npm. Canvas does the drawing, but
 * overlays/legends style their DOM with Tailwind classes under the same
 * contract as @posthog/quill: no pre-compiled stylesheet — the consumer's
 * Tailwind v4 scans our dist JS via the shipped `dist/tailwind.css`
 * `@source` directive. The runtime deps (d3-*, dayjs, @floating-ui/react,
 * simple-statistics) stay external and are redeclared as real
 * `dependencies` so the consumer's package manager installs them; react /
 * react-dom are peers. The dev/story-only entries (testing, story-helpers)
 * are excluded — in-repo consumers reach them via tsconfig path aliases /
 * jest moduleNameMapper against src, not the published package.
 */

// Mirrors @posthog/quill's dist/tailwind.css (see quill/scripts/build-css.ts).
function emitTailwindSource(): Plugin {
    return {
        name: 'emit-tailwind-source',
        closeBundle() {
            const distDir = resolve(__dirname, 'dist')
            mkdirSync(distDir, { recursive: true })
            writeFileSync(
                resolve(distDir, 'tailwind.css'),
                [
                    '/* @posthog/quill-charts — Tailwind source directive.',
                    ' *',
                    ' * Consumer imports this file from their Tailwind v4 entry. The',
                    " * glob path is relative to THIS file's on-disk location (inside",
                    ' * node_modules/@posthog/quill-charts/dist after install), so it',
                    ' * works under pnpm, hoisted, and Docker layouts without needing',
                    ' * consumer-side `../node_modules/...` paths.',
                    ' *',
                    ' * Tailwind scans the compiled library JS for literal class',
                    " * strings and generates the matching utilities in the consumer's",
                    ' * own `utilities` layer — no pre-compiled stylesheet, no',
                    ' * cascade-layer fight with consumer Tailwind output.',
                    ' */',
                    '@source "./**/*.js";',
                    '',
                ].join('\n')
            )
        },
    }
}

export default defineConfig({
    plugins: [
        react(),
        emitTailwindSource(),
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
