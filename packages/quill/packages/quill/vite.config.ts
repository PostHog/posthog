import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

/**
 * Builds the JavaScript entry for @posthog/quill. The CSS pipeline is
 * handled separately by `scripts/build-css.ts` so vite never touches
 * Tailwind or the pre-compiled stylesheet — it only bundles the thin
 * re-export layer that ties primitives + components + blocks together.
 */
export default defineConfig({
    plugins: [
        dts({
            tsconfigPath: resolve(__dirname, 'tsconfig.build.json'),
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
                '@posthog/quill-primitives',
                '@posthog/quill-components',
                '@posthog/quill-blocks',
                '@posthog/quill-tokens',
            ],
        },
        emptyOutDir: false, // dist/quill.css is written by build-css.ts before vite runs
    },
})
