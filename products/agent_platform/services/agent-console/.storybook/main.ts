/**
 * Storybook for the agent platform UI surface.
 *
 * One Storybook, two contributing locations:
 *  - `packages/agent-chat/src/**` for the chat dock stories
 *  - `services/agent-console/src/**` for the console-page stories
 *
 * Story sidebar groups (via `title:` in each .stories.tsx):
 *  - "Agent Chat/*" — chat package
 *  - "Console/Pages/*" — console pages
 *
 * Tailwind v4 is wired via `@tailwindcss/vite`; the import in
 * `.storybook/preview.tsx` of `./storybook.css` pulls in the @theme +
 * @source directives so utilities get generated against both packages'
 * source trees.
 */

import type { StorybookConfig } from '@storybook/react-vite'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Storybook 10 loads main.ts as ESM, so CommonJS globals like __dirname
// don't exist. Re-derive them from import.meta.url.
const __dirname = path.dirname(fileURLToPath(import.meta.url))

const localRequire = createRequire(import.meta.url)
const reactVitePath = path.dirname(localRequire.resolve('@storybook/react-vite/package.json'))

const config: StorybookConfig = {
    stories: [
        '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
        '../../../packages/agent-chat/src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
    ],
    addons: ['@storybook/addon-docs'],
    // `mockServiceWorker.js` is served at `/` so MSW can register the
    // worker. Storybook is the only environment that boots MSW — the
    // Next.js app surface stays MSW-free.
    staticDirs: ['./public'],
    framework: {
        // Pin to this workspace's installed react-vite (v10.x). Without this,
        // storybook's resolver walks up the workspace and can grab an older
        // version brought in by sibling packages (common/storybook, quill/apps/storybook).
        name: reactVitePath,
        options: {},
    },
    viteFinal: async (config) => {
        // `@storybook/react-vite` already registers `@vitejs/plugin-react` —
        // do not add a second instance here or React Refresh double-injects
        // its preamble and Vite chokes on `prevRefreshSig` being redeclared.
        const { default: tailwindcss } = await import('@tailwindcss/vite')

        config.plugins = [...(config.plugins ?? []), tailwindcss()]

        // Force the automatic JSX runtime. tsconfig.json sets `jsx: "preserve"`
        // so esbuild's default JSX mode is *classic* — it emits
        // `React.createElement(...)` and requires `React` to be in scope in
        // every component. Switching to automatic makes esbuild emit
        // `_jsx(...)` from `react/jsx-runtime`, so files don't need an
        // `import React from 'react'` for JSX to work.
        config.esbuild = { ...config.esbuild, jsx: 'automatic' }
        config.resolve = {
            ...config.resolve,
            alias: {
                ...config.resolve?.alias,
                '@': path.resolve(__dirname, '../src'),
                // Storybook runs under Vite, not Next.js. The shell + page
                // clients call `useRouter()` / `<Link>` etc. — stub them out
                // so the real components mount cleanly in stories. `next/link`
                // matters in particular because the real module reads
                // `process.env.*` at module init and crashes the browser
                // bundle with `ReferenceError: process is not defined`.
                'next/navigation': path.resolve(__dirname, './mocks/next-navigation.tsx'),
                'next/link': path.resolve(__dirname, './mocks/next-link.tsx'),
            },
        }
        // Vite pre-bundles deps in `node_modules/.cache/sb-vite/deps/`
        // before applying `resolve.alias`. Excluding the next/* modules
        // here keeps them out of the pre-bundle, so the alias above is
        // what actually resolves the import. (If you ever see the same
        // `process is not defined` error from a fresh next/* import, add
        // it here too.)
        config.optimizeDeps = {
            ...config.optimizeDeps,
            exclude: [...(config.optimizeDeps?.exclude ?? []), 'next/link', 'next/navigation'],
        }
        return config
    },
}

export default config
