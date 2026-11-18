import { cpSync, createReadStream, existsSync, readFileSync, renameSync, statSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { basename, dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Connect, Plugin } from 'vite'

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), '..')

export const MOCK_APP_SHELL = resolve(FRONTEND, 'mock-app.html')
// The fixed-name web workers, which esbuild builds outside Vite (`pnpm build:mock-app:workers`).
const WORKERS_DIR = resolve(FRONTEND, 'dist/mock-app-workers')

// Files the app requests by URL rather than by import, which Django serves in production.
// The first mount that has the file wins.
const MOUNTS: { url: string; dir: string }[] = [
    { url: '/static/hedgehog-mode/', dir: resolve(FRONTEND, 'node_modules/@posthog/hedgehog-mode/assets') },
    { url: '/static/emoji/en/', dir: resolve(FRONTEND, 'node_modules/emojibase-data/en') },
    { url: '/static/', dir: resolve(FRONTEND, 'public') },
    { url: '/static/', dir: WORKERS_DIR },
    { url: '/replay_player_frame/', dir: resolve(FRONTEND, '../posthog/templates/replay_player_frame') },
]

// MSW's service worker must come from the site root, or its scope does not cover the app's URLs.
// The Storybook wrapper lets static files skip the worker and imports MSW's worker.
const STORYBOOK_PUBLIC = resolve(FRONTEND, '../common/storybook/.storybook/public')
const ROOT_FILES = ['storybookServiceWorker.js', 'mockServiceWorker.js']

const CONTENT_TYPES: Record<string, string> = {
    '.css': 'text/css',
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.wasm': 'application/wasm',
    '.webmanifest': 'application/manifest+json',
    '.woff2': 'font/woff2',
}

function findFile(pathname: string): string | null {
    if (ROOT_FILES.some((file) => pathname === `/${file}`)) {
        return join(STORYBOOK_PUBLIC, pathname)
    }
    for (const { url, dir } of MOUNTS) {
        if (pathname.startsWith(url)) {
            const file = resolve(dir, pathname.slice(url.length))
            if (file.startsWith(dir) && existsSync(file) && statSync(file).isFile()) {
                return file
            }
        }
    }
    return null
}

function isPageRequest(request: IncomingMessage, pathname: string): boolean {
    return request.method === 'GET' && !!request.headers.accept?.includes('text/html') && !extname(pathname)
}

/**
 * Runs the app as a static site with mocked API responses (src/mocks/mockApp.ts), with no backend.
 *
 * The dev server serves the URL-addressed files from where they live, and answers every page URL
 * with the shell. The build copies the same files into the output and names the shell index.html,
 * so any static host that falls back to index.html can serve it.
 */
export function mockAppPlugin(): Plugin {
    let outDir = ''
    return {
        name: 'mock-app',
        configResolved(config) {
            outDir = resolve(config.root, config.build.outDir)
        },
        configureServer(server) {
            if (!existsSync(WORKERS_DIR)) {
                server.config.logger.warn(
                    `mock app: ${WORKERS_DIR} is missing, so the web workers will 404. Run \`pnpm build:mock-app:workers\`.`
                )
            }
            server.middlewares.use(async (request: Connect.IncomingMessage, response: ServerResponse, next) => {
                const url = request.url ?? '/'
                const { pathname } = new URL(url, 'http://localhost')
                const file = findFile(pathname)
                if (file) {
                    response.setHeader('Content-Type', CONTENT_TYPES[extname(file)] ?? 'application/octet-stream')
                    createReadStream(file).pipe(response)
                    return
                }
                if (!isPageRequest(request, pathname)) {
                    return next()
                }
                try {
                    const html = await server.transformIndexHtml(url, readFileSync(MOCK_APP_SHELL, 'utf8'))
                    response.setHeader('Content-Type', 'text/html')
                    response.end(html)
                } catch (error) {
                    next(error)
                }
            })
        },
        writeBundle() {
            if (!existsSync(WORKERS_DIR)) {
                throw new Error(`mock app: ${WORKERS_DIR} is missing. Run \`pnpm build:mock-app:workers\` first.`)
            }
            renameSync(join(outDir, basename(MOCK_APP_SHELL)), join(outDir, 'index.html'))
            for (const { url, dir } of [...MOUNTS].reverse()) {
                cpSync(dir, join(outDir, url), { recursive: true })
            }
            for (const file of ROOT_FILES) {
                cpSync(join(STORYBOOK_PUBLIC, file), join(outDir, file))
            }
        },
    }
}
