import type { StorybookConfig } from '@storybook/react-vite'
import { spawn } from 'node:child_process'
import chokidar from 'chokidar'
import path from 'path'
import type { Plugin, ViteDevServer } from 'vite'

/**
 * Regenerates @posthog/quill-tokens dist CSS whenever the tokens source
 * (colors.ts, spacing.ts, typography.ts, …) changes, then triggers a
 * full page reload. Without this plugin the tokens package only rebuilds
 * on explicit `pnpm build`, so runtime CSS custom properties stay stale
 * until the dev server is restarted.
 *
 * Uses a dedicated chokidar watcher instead of `server.watcher.add()`:
 * Vite's default watcher is scoped to the storybook project root and
 * doesn't reliably pick up changes in sibling workspace packages added
 * via globs after server start.
 */
function quillTokensWatcher(): Plugin {
    const tokensRoot = path.resolve(__dirname, '../../../packages/tokens')
    const tokensSrc = path.join(tokensRoot, 'src')
    let rebuildTimer: NodeJS.Timeout | null = null
    let rebuilding = false
    let rebuildPending = false
    let watcher: chokidar.FSWatcher | null = null

    const rebuild = (server: ViteDevServer): void => {
        if (rebuilding) {
            rebuildPending = true
            return
        }
        rebuildPending = false
        rebuilding = true
        console.log('[quill-tokens-watcher] rebuilding tokens…')
        const proc = spawn('pnpm', ['exec', 'tsx', 'src/build.ts'], {
            cwd: tokensRoot,
            stdio: 'inherit',
            shell: true,
        })
        proc.on('error', (err) => {
            console.error('[quill-tokens-watcher] spawn error:', err)
        })
        proc.on('exit', (code) => {
            rebuilding = false
            if (code === 0) {
                console.log('[quill-tokens-watcher] rebuild ok → reloading')
                server.ws.send({ type: 'full-reload' })
            } else {
                console.error('[quill-tokens-watcher] rebuild failed, exit', code)
            }
            if (rebuildPending) {
                rebuild(server)
            }
        })
    }

    return {
        name: 'quill-tokens-watcher',
        configureServer(server) {
            watcher = chokidar.watch(tokensSrc, {
                ignored: /node_modules/,
                ignoreInitial: true,
                awaitWriteFinish: { stabilityThreshold: 50, pollInterval: 20 },
            })
            watcher.on('all', (event, file) => {
                if (event !== 'change' && event !== 'add') {
                    return
                }
                if (!file.endsWith('.ts')) {
                    return
                }
                if (rebuildTimer) {
                    clearTimeout(rebuildTimer)
                }
                rebuildTimer = setTimeout(() => rebuild(server), 100)
            })
            watcher.on('ready', () => {
                console.log('[quill-tokens-watcher] watching', tokensSrc)
            })
        },
        closeBundle() {
            watcher?.close()
        },
    }
}

const config: StorybookConfig = {
    stories: [
        '../stories/**/*.mdx',
        '../stories/**/*.stories.@(js|jsx|mjs|ts|tsx)',
        // Also pick up stories co-located in packages
        '../../../packages/*/src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
    ],
    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-toolbars',
        'storybook-addon-pseudo-states',
        'storybook-dark-mode',
    ],
    framework: {
        name: '@storybook/react-vite',
        options: {},
    },
    viteFinal: async (config) => {
        const { default: tailwindcss } = await import('@tailwindcss/vite')

        config.plugins = [...(config.plugins || []), tailwindcss(), quillTokensWatcher()]
        config.resolve = {
            ...config.resolve,
            alias: {
                ...config.resolve?.alias,
                // Points to primitives/src so @/ imports in primitive components resolve
                '@': path.resolve(__dirname, '../../../packages/primitives/src'),
            },
        }

        return config
    },
}

export default config
