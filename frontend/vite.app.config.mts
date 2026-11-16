import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadConfigFromFile, type Plugin, type PluginOption, type UserConfig } from 'vite'

import { chunkGraphPlugin, textFilesPlugin, zodEnLocaleOnlyPlugin } from './plugins/vite-app-build'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Must match VITE_APP_DIR in bin/viteAppBuild.mjs and the manifest path in posthog/vite_app.py.
const OUT_DIR = 'dist/vite'

// These plugins of the dev server config write into dist/ and src/assets/ when they start, which a
// production build must not do: dist/ also holds the esbuild build.
const DEV_SERVER_ONLY_PLUGINS = new Set(['html-generation', 'posthog-js-copy', 'public-assets-copy', 'startup-message'])

async function flattenPlugins(plugins: PluginOption[] | undefined): Promise<Plugin[]> {
    const flat: Plugin[] = []
    for (const plugin of plugins ?? []) {
        const resolved = await plugin
        if (Array.isArray(resolved)) {
            flat.push(...(await flattenPlugins(resolved)))
        } else if (resolved) {
            flat.push(resolved as Plugin)
        }
    }
    return flat
}

/**
 * The production build of the app entry with Vite. `pnpm build:vite-app` runs it, and then
 * bin/viteAppBuild.mjs, which prepares the output for the backend (posthog/vite_app.py).
 * It reuses the dev server config, so a module resolves the same way in both.
 */
export default defineConfig(async (env): Promise<UserConfig> => {
    const devServerConfig = await loadConfigFromFile(env, resolve(__dirname, 'vite.config.mts'))
    if (!devServerConfig) {
        throw new Error('vite app: cannot load vite.config.mts')
    }
    const base = devServerConfig.config
    const plugins = (await flattenPlugins(base.plugins)).filter((plugin) => !DEV_SERVER_ONLY_PLUGINS.has(plugin.name))

    return {
        ...base,
        base: '/static/vite/',
        // Vite refuses an import of a file in its public directory, and app code imports from
        // frontend/public. The dev server avoids this with a copy in src/assets. The build reads
        // frontend/public as source instead.
        publicDir: false,
        plugins: [textFilesPlugin(), zodEnLocaleOnlyPlugin(), ...plugins, chunkGraphPlugin()],
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
        assetsInclude: ['**/*.bin'],
        experimental: {
            ...base.experimental,
            // The asset host (JS_URL) is known only at runtime: PostHog Cloud serves the files of one
            // image from a CDN. `base` alone would send every stylesheet and image that JS code asks
            // for to the app's own origin. The boot script defines the function
            // (posthog/templates/vite_app_boot.html). A URL inside a stylesheet stays relative to
            // that stylesheet, which already comes from the asset host.
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
