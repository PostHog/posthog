#!/usr/bin/env node
/* eslint-disable no-console */

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
 *   --site-url <url>          Site URL for origin (default: http://localhost:8010)
 *   --team-id <n>             Team ID (default: 1)
 *   --screenshot-dir <d>      Directory for screenshots (default: /tmp/replay-screenshots)
 *   --screenshot-ms <n>       Screenshot interval in ms (default: 2000)
 *   --headless                Run headless (default: false, so you can watch)
 *   --viewport <WxH>          Browser viewport size (default: 1920x1080)
 */

import { readFileSync, mkdirSync } from 'fs'
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
        siteUrl: 'http://localhost:8010',
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
        } else if (args[i] === '--site-url') {
            config.siteUrl = args[++i]
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

function elapsed(startMs) {
    return `${((performance.now() - startMs) / 1000).toFixed(1)}s`
}

async function main() {
    const startTime = performance.now()
    const config = parseArgs(process.argv.slice(2))

    if (!config.sessionId) {
        console.error(
            'Usage: node test-puppeteer.mjs <session_id> [--speed 4] [--recording-api-url http://localhost:6738] [--headless] [--viewport 1920x1080]'
        )
        process.exit(1)
    }

    console.log(`[test] session=${config.sessionId} team=${config.teamId} speed=${config.speed}x`)
    console.log(`[test] recording-api=${config.recordingApiUrl} site-url=${config.siteUrl}`)
    console.log(`[test] viewport=${config.viewportWidth}x${config.viewportHeight}`)
    console.log(`[test] screenshots → ${config.screenshotDir} (every ${config.screenshotMs}ms)`)

    const playerConfig = {
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

    const playerUrl = `${config.siteUrl}/player.html`

    mkdirSync(config.screenshotDir, { recursive: true })

    console.log(`[test] launching browser (headless=${config.headless})...`)
    const browser = await puppeteer.launch({
        headless: config.headless,
        executablePath:
            process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined,
        args: [
            `--window-size=${config.viewportWidth},${config.viewportHeight}`,
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--autoplay-policy=no-user-gesture-required',
            '--disable-web-security',
        ],
    })

    const page = await browser.newPage()
    await page.setViewport({ width: config.viewportWidth, height: config.viewportHeight })

    await page.setRequestInterception(true)
    page.on('request', (req) => {
        if (req.url() === playerUrl) {
            req.respond({ status: 200, contentType: 'text/html', body: injectedHtml })
        } else {
            req.continue()
        }
    })

    page.on('console', (msg) => {
        const level = msg.type() === 'error' ? 'error' : msg.type() === 'warning' ? 'warn' : 'log'
        console[level](`[browser] ${msg.text()}`)
    })

    page.on('pageerror', (err) => {
        console.error(`[browser error] ${err.message}`)
    })

    page.on('response', (res) => {
        if (res.status() >= 400) {
            console.error(`[http ${res.status()}] ${res.url()}`)
        }
    })

    console.log(`[test] navigating to ${playerUrl} ...`)
    await page.goto(playerUrl, { waitUntil: 'domcontentloaded' })
    console.log(`[test] page loaded (origin=${new URL(playerUrl).origin}), waiting for playback to start...`)

    await page.waitForFunction(() => window.__POSTHOG_SEGMENT_COUNTER__ > 0, {
        timeout: 60 * 1000,
        polling: 200,
    })
    console.log(`[test] playback started`)

    let screenshotCount = 0
    let stopped = false
    const screenshotInterval = setInterval(async () => {
        if (stopped) {
            return
        }
        try {
            const segment = await page.evaluate(() => window.__POSTHOG_SEGMENT_COUNTER__)
            screenshotCount++
            const path = `${config.screenshotDir}/frame-${String(screenshotCount).padStart(4, '0')}.png`
            await page.screenshot({ path })
            console.log(`[test] screenshot #${screenshotCount} (segment=${segment ?? '?'}) → ${path}`)
        } catch {
            // page might be closing
        }
    }, config.screenshotMs)

    // Wait for playback to finish
    let timedOut = false
    try {
        await page.waitForFunction(() => window.__POSTHOG_RECORDING_ENDED__ === true, {
            timeout: 10 * 60 * 1000, // 10 min max
            polling: 500,
        })
        console.log(`[test] playback finished (${elapsed(startTime)})`)
    } catch {
        timedOut = true
        console.warn(`[test] playback timed out after 10 minutes`)
    }

    stopped = true
    clearInterval(screenshotInterval)

    // Final screenshot
    screenshotCount++
    const finalPath = `${config.screenshotDir}/frame-${String(screenshotCount).padStart(4, '0')}-final.png`
    await page.screenshot({ path: finalPath })
    console.log(`[test] final screenshot → ${finalPath}`)

    // Print summary
    const periods = await page.evaluate(() => window.__POSTHOG_INACTIVITY_PERIODS__)
    const segments = await page.evaluate(() => window.__POSTHOG_SEGMENT_COUNTER__)

    console.log(`[test] --- summary ---`)
    console.log(`[test] total segments: ${segments ?? 'unknown'}`)
    console.log(`[test] total screenshots: ${screenshotCount}`)
    if (periods && periods.length > 0) {
        const active = periods.filter((p) => p.active).length
        const inactive = periods.filter((p) => !p.active).length
        console.log(`[test] activity periods: ${active} active, ${inactive} inactive`)
    }
    console.log(`[test] total time: ${elapsed(startTime)}`)
    if (timedOut) {
        console.log(`[test] recording did not finish within timeout`)
    }

    await browser.close()
    process.exit(0)
}

main().catch((err) => {
    console.error(err.message)
    process.exit(1)
})
