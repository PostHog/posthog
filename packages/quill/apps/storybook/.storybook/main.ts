import type { StorybookConfig } from '@storybook/react-vite'
import { spawn } from 'node:child_process'
import path from 'path'
import type { Plugin, ViteDevServer } from 'vite'

/**
 * Regenerates @posthog/quill-tokens dist CSS whenever the tokens source
 * (colors.ts, spacing.ts, typography.ts, …) changes, then triggers a
 * full page reload. Without this plugin the tokens package only rebuilds
 * on explicit `pnpm build`, so runtime CSS custom properties stay stale
 * until the dev server is restarted.
 */
function quillTokensWatcher(): Plugin {
    const tokensRoot = path.resolve(__dirname, '../../../packages/tokens')
    const tokensSrc = path.join(tokensRoot, 'src')
    let rebuildTimer: NodeJS.Timeout | null = null
    let rebuilding = false
    let rebuildPending = false

    const rebuild = (server: ViteDevServer): void => {
        if (rebuilding) {
            rebuildPending = true
            return
        }
        rebuildPending = false
        rebuilding = true
        const proc = spawn('pnpm', ['exec', 'tsx', 'src/build.ts'], {
            cwd: tokensRoot,
            stdio: 'inherit',
            shell: true,
        })
        proc.on('exit', (code) => {
            rebuilding = false
            if (code === 0) {
                server.ws.send({ type: 'full-reload' })
            }
            if (rebuildPending) {
                rebuild(server)
            }
        })
    }

    return {
        name: 'quill-tokens-watcher',
        configureServer(server) {
            server.watcher.add(path.join(tokensSrc, '**/*.ts'))
            server.watcher.on('change', (file) => {
                if (!file.startsWith(tokensSrc)) {
                    return
                }
                if (rebuildTimer) {
                    clearTimeout(rebuildTimer)
                }
                rebuildTimer = setTimeout(() => rebuild(server), 100)
            })
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
    addons: ['@storybook/addon-docs', '@storybook/addon-toolbars', 'storybook-addon-pseudo-states'],
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
