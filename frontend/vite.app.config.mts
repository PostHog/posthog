import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadConfigFromFile, type UserConfig } from 'vite'

import { URL_PREFIX, VITE_APP_DIR } from './bin/viteAppBuild.mjs'
import { chunkGraphPlugin, textFilesPlugin, zodEnLocaleOnlyPlugin } from './plugins/vite-app-build'
import { WORKER_FILES_META } from './workers.config.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))

// posthog/vite_app.py reads the manifest from this directory.
const OUT_DIR = `dist/${VITE_APP_DIR}`

/**
 * The hashed worker file names from the esbuild build, for `createWorker` (src/lib/utils/createWorker.ts).
 * The esbuild build makes the workers, so it has to run first. Without its file, or for a worker whose
 * hashed file is gone, the app loads the worker by its fixed name, which a deploy overwrites in place.
 */
function hashedWorkerFiles(): Record<string, string> | undefined {
    const metaPath = resolve(__dirname, WORKER_FILES_META)
    if (!existsSync(metaPath)) {
        console.warn(
            `vite app: ${WORKER_FILES_META} is missing, so workers load by their fixed names. Run \`pnpm build\` first.`
        )
        return undefined
    }
    const files: Record<string, string> = JSON.parse(readFileSync(metaPath, 'utf8'))
    return Object.fromEntries(
        Object.entries(files).filter(([, hashedName]) => existsSync(resolve(__dirname, 'dist', hashedName)))
    )
}

export default defineConfig(async (env): Promise<UserConfig> => {
    // The build reuses the dev server config, so a module resolves the same way in both.
    const devServerConfig = await loadConfigFromFile(env, resolve(__dirname, 'vite.config.mts'))
    if (!devServerConfig) {
        throw new Error('vite app: cannot load vite.config.mts')
    }
    const base = devServerConfig.config
    const workerFiles = hashedWorkerFiles()

    return {
        ...base,
        base: `/${URL_PREFIX}`,
        // Vite refuses an import of a file in its public directory, and app code imports from
        // frontend/public. The dev server avoids this with a copy in src/assets. The build reads
        // frontend/public as source instead.
        publicDir: false,
        // The plugins of the dev server config that write into dist/ and src/assets/ apply to `serve` only.
        plugins: [textFilesPlugin(), zodEnLocaleOnlyPlugin(), ...(base.plugins ?? []), chunkGraphPlugin()],
        resolve: {
            ...base.resolve,
            alias: {
                ...(base.resolve?.alias as Record<string, string>),
                public: resolve(__dirname, 'public'),
                // The same Node polyfills as the esbuild build (common/esbuilder/utils.mjs).
                crypto: 'crypto-browserify',
                'node:crypto': 'crypto-browserify',
                stream: 'stream-browserify',
            },
        },
        define: {
            ...base.define,
            ...(workerFiles ? { __POSTHOG_WORKER_FILES__: JSON.stringify(workerFiles) } : {}),
        },
        assetsInclude: ['**/*.bin'],
        experimental: {
            ...base.experimental,
            // The asset host (JS_URL) is known only at runtime: PostHog Cloud serves the files of one
            // image from a CDN. `base` alone would send every stylesheet and image that JS code asks
            // for to the app's own origin. The boot script defines the function
            // (posthog/templates/vite_app_boot.html). A URL inside a stylesheet stays relative to
            // that stylesheet, which already comes from the asset host.
            // Vite warns that it does not support this option together with `chunkImportMap`. Chunks
            // still import each other by relative paths, so the import map never sees these URLs.
            renderBuiltUrl(filename, { hostType }) {
                return hostType === 'js'
                    ? { runtime: `window.VITE_APP_ASSET_URL(${JSON.stringify(filename)})` }
                    : { relative: true }
            },
        },
        css: {
            ...base.css,
            preprocessorOptions: { less: { javascriptEnabled: true } },
        },
        build: {
            outDir: OUT_DIR,
            emptyOutDir: true,
            manifest: true,
            sourcemap: true,
            // Chunks import each other through placeholder names, and an import map resolves each
            // placeholder to its file. A changed chunk then gets a new file name without a change
            // to the chunks that import it, so returning users keep those in their cache.
            chunkImportMap: true,
            // Vite puts the list of files to preload into each module that has a dynamic import.
            // For the two scene registries that is one list per scene, on the boot path. The
            // external chunk map from bin/viteAppBuild.mjs carries the same lists off that path.
            modulePreload: false,
            chunkSizeWarningLimit: 10_000,
            rollupOptions: {
                input: { index: resolve(__dirname, 'src/index.tsx') },
                output: {
                    // With short export names, a new export in one chunk renames the exports that
                    // other chunks import from it, and each of those chunks gets a new file name.
                    minifyInternalExports: false,
                    entryFileNames: '[name]-[hash].js',
                    chunkFileNames: 'chunk-[hash].js',
                    assetFileNames: 'assets/[name]-[hash].[ext]',
                },
            },
        },
    }
})
