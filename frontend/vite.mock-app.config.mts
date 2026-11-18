import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadConfigFromFile, type PluginOption, type UserConfig } from 'vite'

import { MOCK_APP_PORT } from './bin/mockApp.mjs'
import { MOCK_APP_SHELL, mockAppPlugin } from './plugins/vite-mock-app'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Plugins of the base configs that write files for Django and the app build's file step, or send
// people to Django's port.
const BACKEND_PLUGINS = new Set([
    'html-generation',
    'public-assets-copy',
    'posthog-js-copy',
    'startup-message',
    'chunk-graph',
])

async function withoutBackendPlugins(plugins: PluginOption[]): Promise<PluginOption[]> {
    const resolved = (await Promise.all(plugins)).flat(Infinity as 1) as PluginOption[]
    return resolved.filter((plugin) => !(plugin && 'name' in plugin && BACKEND_PLUGINS.has(plugin.name)))
}

// The app behind a static shell with mocked API responses. It shares the plugins, aliases and module
// resolution of the app's Vite build (vite.app.config.mts) but replaces its whole `build` block, so it is
// not the production build: it has no import map and uses Vite's default preload lists.
export default defineConfig(async (env): Promise<UserConfig> => {
    const appConfig = await loadConfigFromFile(env, resolve(__dirname, 'vite.app.config.mts'))
    if (!appConfig) {
        throw new Error('mock app: cannot load vite.app.config.mts')
    }
    const base = appConfig.config
    const server = { port: MOCK_APP_PORT, strictPort: true, host: 'localhost' }

    return {
        ...base,
        base: '/',
        // The dev server's pre-bundled dependencies differ, and two servers that share a cache overwrite each other's.
        cacheDir: 'node_modules/.vite-mock-app',
        plugins: [...(await withoutBackendPlugins(base.plugins ?? [])), mockAppPlugin()],
        // The app build loads its files from an asset host that only Django knows. This site serves them itself.
        experimental: { ...base.experimental, renderBuiltUrl: undefined },
        // The app config names the hashed worker files of the esbuild build when that build has run. This
        // site serves only the fixed names, and without the define the app asks for those.
        define: Object.fromEntries(
            Object.entries(base.define ?? {}).filter(([name]) => name !== '__POSTHOG_WORKER_FILES__')
        ),
        server,
        preview: server,
        build: {
            outDir: 'dist/mock-app',
            emptyOutDir: true,
            sourcemap: true,
            chunkSizeWarningLimit: 10_000,
            rollupOptions: { input: { index: MOCK_APP_SHELL } },
        },
    }
})
