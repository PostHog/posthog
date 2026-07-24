import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

import baseConfigFactory from './vite.config.mts'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Standalone build for the embeddable widgets bundle (src/widgets/index.tsx).
//
// Produces dist-widgets/widgets.js (ESM entry, code-split chunks alongside) and
// dist-widgets/widgets.css (single stylesheet the widget links into its shadow
// root). Serve the directory statically (bin/serve-widgets.mjs) and load
// widgets.js as a module script from any host app.
//
//   pnpm --filter=@posthog/frontend exec vite build --config vite.widgets.config.mts
export default defineConfig((env) => {
    const base = baseConfigFactory(env) as Record<string, any>

    return {
        ...base,
        plugins: base.plugins,
        build: {
            outDir: 'dist-widgets',
            emptyOutDir: true,
            manifest: false,
            sourcemap: false,
            // One stylesheet for the whole bundle — the shadow root links it once.
            cssCodeSplit: false,
            rollupOptions: {
                input: { widgets: resolve(__dirname, 'src/widgets/index.tsx') },
                output: {
                    entryFileNames: 'widgets.js',
                    chunkFileNames: 'chunks/[name]-[hash].js',
                    assetFileNames: (assetInfo: { names?: string[] }) => {
                        const name = assetInfo.names?.[0] ?? ''
                        return name.endsWith('.css') ? 'widgets.css' : 'assets/[name]-[hash][extname]'
                    },
                },
            },
        },
    }
})
