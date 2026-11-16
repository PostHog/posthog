import { readFileSync } from 'fs'
import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import path from 'path'

import { CARDS_DIR, catalogOf } from './catalog'
import { listRuns, runDetailOf } from './runs'

const STATIC_DIR = path.join(__dirname, 'static')

const STATIC_FILES: Record<string, { file: string; type: string }> = {
    '/': { file: 'index.html', type: 'text/html; charset=utf-8' },
    '/app.js': { file: 'app.js', type: 'text/javascript; charset=utf-8' },
    '/app.css': { file: 'app.css', type: 'text/css; charset=utf-8' },
}

export type ViewerOptions = { stateDir: string; cardsDir?: string }

function send(response: ServerResponse, status: number, type: string, body: string): void {
    response.writeHead(status, { 'content-type': type, 'cache-control': 'no-store' })
    response.end(body)
}

const sendJson = (response: ServerResponse, status: number, value: unknown): void =>
    send(response, status, 'application/json; charset=utf-8', JSON.stringify(value))

// The viewer only reads: cards from the checkout and evidence from the state directory. Static
// files are read per request, so an edit to the page shows on the next reload.
export function createViewerServer({ stateDir, cardsDir = CARDS_DIR }: ViewerOptions): Server {
    const handle = (request: IncomingMessage, response: ServerResponse): void => {
        if (request.method !== 'GET') {
            return sendJson(response, 405, { error: 'the viewer only answers GET' })
        }
        const { pathname } = new URL(request.url ?? '/', 'http://viewer')
        const asset = STATIC_FILES[pathname]
        if (asset) {
            return send(response, 200, asset.type, readFileSync(path.join(STATIC_DIR, asset.file), 'utf8'))
        }
        if (pathname === '/api/cards') {
            return sendJson(response, 200, catalogOf(cardsDir))
        }
        if (pathname === '/api/runs') {
            return sendJson(response, 200, listRuns(stateDir))
        }
        const run = /^\/api\/runs\/([^/]+)$/.exec(pathname)
        if (run) {
            const detail = runDetailOf(stateDir, run[1])
            return detail ? sendJson(response, 200, detail) : sendJson(response, 404, { error: 'no such run' })
        }
        sendJson(response, 404, { error: 'not found' })
    }
    return createServer((request, response) => {
        try {
            handle(request, response)
        } catch (error) {
            sendJson(response, 500, { error: (error as Error).message })
        }
    })
}
