#!/usr/bin/env node

/**
 * Test the headless replay player with Puppeteer, mimicking how the rasterizer runs it.
 *
 * Usage:
 *   node test-puppeteer.mjs <session_id> [options]
 *
 * Options:
 *   --speed <n>               Playback speed (default: 4)
 *   --recording-api-url <url> Recording API URL (default: http://localhost:6738)
 *   --recording-api-secret <s> Internal API secret (default: posthog123)
 *   --clickhouse-url <url>    ClickHouse HTTP URL (default: http://localhost:8123)
 *   --team-id <n>             Team ID (default: 1)
 *   --screenshot-dir <d>      Directory for screenshots (default: /tmp/replay-screenshots)
 *   --screenshot-ms <n>       Screenshot interval in ms (default: 2000)
 *   --headless                Run headless (default: false, so you can watch)
 *   --viewport <WxH>          Browser viewport size (default: 1920x1080)
 */

import { readFileSync, mkdirSync } from 'fs'
import { createServer } from 'http'
import { resolve, dirname } from 'path'
import puppeteer from 'puppeteer'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

function parseArgs(args) {
    const config = {
        sessionId: null,
        speed: 4,
        recordingApiUrl: 'http://localhost:6738',
        recordingApiSecret: 'posthog123',
        clickhouseUrl: 'http://localhost:8123',
        teamId: 1,
        screenshotDir: '/tmp/replay-screenshots',
        screenshotMs: 2000,
        headless: false,
        viewportWidth: 1920,
        viewportHeight: 1080,
        skipInactivity: false,
        noMouseTail: false,
        startTimestamp: undefined,
        endTimestamp: undefined,
    }

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--speed') {
            config.speed = Number(args[++i])
        } else if (args[i] === '--recording-api-url') {
            config.recordingApiUrl = args[++i]
        } else if (args[i] === '--recording-api-secret') {
            config.recordingApiSecret = args[++i]
        } else if (args[i] === '--clickhouse-url') {
            config.clickhouseUrl = args[++i]
        } else if (args[i] === '--team-id') {
            config.teamId = Number(args[++i])
        } else if (args[i] === '--screenshot-dir') {
            config.screenshotDir = args[++i]
        } else if (args[i] === '--screenshot-ms') {
            config.screenshotMs = Number(args[++i])
        } else if (args[i] === '--headless') {
            config.headless = true
        } else if (args[i] === '--skip-inactivity') {
            config.skipInactivity = true
        } else if (args[i] === '--no-mouse-tail') {
            config.noMouseTail = true
        } else if (args[i] === '--start-ts') {
            config.startTimestamp = Number(args[++i])
        } else if (args[i] === '--end-ts') {
            config.endTimestamp = Number(args[++i])
        } else if (args[i] === '--viewport') {
            const [w, h] = args[++i].split('x').map(Number)
            config.viewportWidth = w
            config.viewportHeight = h
        } else if (!args[i].startsWith('-')) {
            config.sessionId = args[i]
        }
    }

    return config
}

async function fetchBlockUrls(config) {
    const query = `
        SELECT groupArrayArray(block_urls) as block_urls
        FROM session_replay_events
        WHERE team_id = ${config.teamId}
        AND session_id = '${config.sessionId}'
        GROUP BY session_id
        FORMAT JSON
    `
    const response = await fetch(`${config.clickhouseUrl}/?query=${encodeURIComponent(query.trim())}`)
    if (!response.ok) {
        throw new Error(`ClickHouse query failed: ${response.status} ${await response.text()}`)
    }
    const data = await response.json()
    if (!data.data || data.data.length === 0) {
        throw new Error('No blocks found in ClickHouse for this session')
    }
    return data.data[0].block_urls
}

function parseBlockUrl(blockUrl) {
    const url = new URL(blockUrl)
    const key = url.pathname.replace(/^\//, '')
    const rangeMatch = url.search.match(/range=bytes=(\d+)-(\d+)/)
    if (!rangeMatch) {
        throw new Error(`Invalid block URL range: ${blockUrl}`)
    }
    return { key, start: parseInt(rangeMatch[1]), end: parseInt(rangeMatch[2]) }
}

function startServer(playerHtml, port) {
    return new Promise((resolve) => {
        const server = createServer((req, res) => {
            if (req.url === '/' || req.url === '/player.html') {
                res.writeHead(200, { 'Content-Type': 'text/html' })
                res.end(playerHtml)
                return
            }
            res.writeHead(404)
            res.end('Not found')
        })
        server.listen(port, () => resolve(server))
    })
}

async function main() {
    const config = parseArgs(process.argv.slice(2))

    if (!config.sessionId) {
        console.error(
            'Usage: node test-puppeteer.mjs <session_id> [--speed 4] [--recording-api-url http://localhost:6738] [--headless] [--viewport 1920x1080]'
        )
        process.exit(1)
    }

    const blockUrls = await fetchBlockUrls(config)
    const blocks = blockUrls.map(parseBlockUrl)

    const playerConfig = {
        blocks,
        recordingApiBaseUrl: config.recordingApiUrl,
        recordingApiSecret: config.recordingApiSecret,
        teamId: config.teamId,
        sessionId: config.sessionId,
        playbackSpeed: config.speed,
        skipInactivity: config.skipInactivity,
        mouseTail: !config.noMouseTail,
        startTimestamp: config.startTimestamp,
        endTimestamp: config.endTimestamp,
    }

    const playerHtml = readFileSync(resolve(__dirname, 'dist/player.html'), 'utf-8')
    const configScript = `
        <script>
            window.__POSTHOG_PLAYER_CONFIG__ = ${JSON.stringify(playerConfig)};
            window.dispatchEvent(new Event('posthog-player-init'));
        </script>
    `
    const injectedHtml = playerHtml.replace('</body>', `${configScript}</body>`)

    const server = await startServer(injectedHtml, 3124)

    mkdirSync(config.screenshotDir, { recursive: true })

    const browser = await puppeteer.launch({
        headless: config.headless,
        executablePath:
            process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined,
        args: [
            `--window-size=${config.viewportWidth},${config.viewportHeight}`,
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--autoplay-policy=no-user-gesture-required',
        ],
    })

    const page = await browser.newPage()
    await page.setViewport({ width: config.viewportWidth, height: config.viewportHeight })

    page.on('console', async (msg) => {
        const args = await Promise.all(msg.args().map((a) => a.jsonValue().catch(() => a.toString())))
    })

    page.on('pageerror', (err) => {
        console.error(`[browser error] ${err.message}`)
    })

    page.on('response', (res) => {
        if (res.status() >= 400) {
            console.error(`[http ${res.status()}] ${res.url()}`)
        }
    })

    await page.goto('http://localhost:3124/player.html', { waitUntil: 'domcontentloaded' })

    let screenshotCount = 0
    const screenshotInterval = setInterval(async () => {
        try {
            const segmentCounter = await page.evaluate(() => window.__POSTHOG_SEGMENT_COUNTER__)
            const currentTs = await page.evaluate(() => window.__POSTHOG_CURRENT_SEGMENT_START_TS__)
            screenshotCount++
            const path = `${config.screenshotDir}/frame-${String(screenshotCount).padStart(4, '0')}.png`
            await page.screenshot({ path })
        } catch {
            // page might be navigating
        }
    }, config.screenshotMs)

    // Wait for playback to finish

    try {
        await page.waitForFunction(() => window.__POSTHOG_RECORDING_ENDED__ === true, {
            timeout: 10 * 60 * 1000, // 10 min max
            polling: 500,
        })
    } catch {}

    clearInterval(screenshotInterval)

    // Final screenshot
    screenshotCount++
    const finalPath = `${config.screenshotDir}/frame-${String(screenshotCount).padStart(4, '0')}-final.png`
    await page.screenshot({ path: finalPath })

    // Print summary
    const periods = await page.evaluate(() => window.__POSTHOG_INACTIVITY_PERIODS__)
    const segments = await page.evaluate(() => window.__POSTHOG_SEGMENT_COUNTER__)

    await browser.close()
    server.close()
}

main().catch((err) => {
    console.error(err.message)
    process.exit(1)
})
