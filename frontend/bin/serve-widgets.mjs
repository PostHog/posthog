#!/usr/bin/env node
// Tiny static server for the built widgets bundle (dist-widgets/) with permissive
// CORS — module scripts and their chunks are CORS-gated cross-origin, and host
// apps (PostHog Code desktop, harness pages) load from a different origin.
//
//   node bin/serve-widgets.mjs [port]   (default 8124)
import * as fs from 'node:fs'
import * as http from 'node:http'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const distDir = path.resolve(__dirname, '..', 'dist-widgets')
const port = Number(process.argv[2] || 8124)

const MIME = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
    '.html': 'text/html',
    '.json': 'application/json',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.map': 'application/json',
    '.wasm': 'application/wasm',
}

http.createServer((req, res) => {
    const urlPath = decodeURIComponent(new URL(req.url, 'http://x').pathname)
    const effectivePath = urlPath === '/' || urlPath === '/harness.html' ? '/harness.html' : urlPath
    // The harness lives in src/widgets (it survives emptyOutDir); everything else in dist-widgets.
    const baseDir = effectivePath === '/harness.html' ? path.resolve(__dirname, '..', 'src', 'widgets') : distDir
    let filePath = path.normalize(path.join(baseDir, effectivePath))
    if (!filePath.startsWith(baseDir)) {
        res.writeHead(403)
        res.end()
        return
    }
    fs.readFile(filePath, (err, data) => {
        if (err) {
            res.writeHead(404, { 'Access-Control-Allow-Origin': '*' })
            res.end('not found: ' + urlPath)
            return
        }
        res.writeHead(200, {
            'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-cache',
        })
        res.end(data)
    })
}).listen(port, () => {
    console.log(`[serve-widgets] http://localhost:${port} -> ${distDir}`)
})
