import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

/**
 * Builds the JavaScript entry for @posthog/quill. The CSS pipeline is
 * handled separately by `scripts/build-css.ts` which just emits the
 * tokens / base / tailwind.css metadata files — vite never runs
 * Tailwind. It only bundles the thin re-export layer that ties
 * primitives + components + blocks together.
 *
 * IMPORTANT: `@posthog/quill-primitives`, `@posthog/quill-components`,
 * and `@posthog/quill-blocks` are **not** externalized. They are
 * `private: true` workspace packages that never ship to npm, so the
 * aggregate has to inline their code at build time — otherwise the
 * published dist would have `import from '@posthog/quill-primitives'`
 * statements pointing at a package that does not exist in the registry
 * and consumers would get ERR_MODULE_NOT_FOUND on first import.
 *
 * `@posthog/quill-tokens` stays external because it is independently
 * published. Actual runtime deps (@base-ui/react, cmdk, lucide-react,
 * etc.) are kept external too — they are redeclared as real
 * `dependencies` on the aggregate's package.json so pnpm/npm pulls
 * them into the consumer's node_modules automatically.
 */
export default defineConfig({
    plugins: [
        dts({
            tsconfigPath: resolve(__dirname, 'tsconfig.build.json'),
            // Same reason as the rollup `external` list below: the type
            // definitions re-exported from the private sub-packages have
            // to be inlined into dist/index.d.ts, otherwise consumers get
            // TypeScript resolution errors trying to find types in
            // @posthog/quill-primitives / -components / -blocks (which
            // are not published to npm). `bundledPackages` tells
            // api-extractor to follow and inline their .d.ts trees
            // instead of treating them as externals.
            rollupTypes: true,
            bundledPackages: ['@posthog/quill-primitives', '@posthog/quill-components', '@posthog/quill-blocks'],
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
                '@posthog/quill-tokens',
                '@base-ui/react',
                /^@base-ui\/react\//,
                'class-variance-authority',
                'clsx',
                'cmdk',
                'lucide-react',
                'react-resizable-panels',
                'tailwind-merge',
                'vaul',
            ],
        },
        // scripts/build-css.ts writes dist/{tokens,base,tailwind,color-system}.css
        // before vite runs — don't let vite wipe them.
        emptyOutDir: false,
    },
})
