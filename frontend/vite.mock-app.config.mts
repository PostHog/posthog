import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadConfigFromFile, type PluginOption, type UserConfig } from 'vite'

import { MOCK_APP_PORT } from './bin/mockApp.mjs'
import { MOCK_APP_SHELL, mockAppPlugin } from './plugins/vite-mock-app'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Plugins of the base configs that write files for Django or send people to its port.
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

// The production Vite build (vite.app.config.mts), behind a static shell with mocked API responses.
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
