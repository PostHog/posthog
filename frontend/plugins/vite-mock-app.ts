import { cpSync, createReadStream, existsSync, readFileSync, renameSync, statSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { basename, dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Connect, Plugin } from 'vite'

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), '..')

export const MOCK_APP_SHELL = resolve(FRONTEND, 'mock-app.html')
const WORKERS_DIR = resolve(FRONTEND, 'dist/mock-app-workers')

// Files the app requests by URL, which Django serves in production. The first mount with the file wins.
const MOUNTS: { url: string; dir: string }[] = [
    { url: '/static/hedgehog-mode/', dir: resolve(FRONTEND, 'node_modules/@posthog/hedgehog-mode/assets') },
    { url: '/static/emoji/en/', dir: resolve(FRONTEND, 'node_modules/emojibase-data/en') },
    { url: '/static/', dir: resolve(FRONTEND, 'public') },
    { url: '/static/', dir: WORKERS_DIR },
    { url: '/replay_player_frame/', dir: resolve(FRONTEND, '../posthog/templates/replay_player_frame') },
]

// MSW's service worker must come from the site root, or its scope does not cover the app's URLs.
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

function notFound(response: ServerResponse): void {
    response.statusCode = 404
    response.end()
}

function isPageRequest(request: IncomingMessage, pathname: string): boolean {
    return request.method === 'GET' && !!request.headers.accept?.includes('text/html') && !extname(pathname)
}

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
                // Vite would answer a missing file with the shell, which hides it from the browser.
                if (MOUNTS.some(({ url }) => pathname.startsWith(url))) {
                    return notFound(response)
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
        configurePreviewServer(server) {
            // Preview answers unknown URLs with index.html and a 200, which would hide a missing file.
            server.middlewares.use((request: Connect.IncomingMessage, response: ServerResponse, next) => {
                const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname)
                const ext = extname(pathname)
                const file = resolve(outDir, `.${pathname}`)
                if (ext && ext !== '.html' && (!file.startsWith(outDir) || !existsSync(file))) {
                    return notFound(response)
                }
                next()
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
