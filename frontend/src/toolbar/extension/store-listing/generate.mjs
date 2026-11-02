import { chromium } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

// Renders the extension's store listing images into ./images. See "Store listing images" in ../README.md.
import { roundHogBoldUrl, roundHogMediumUrl } from '@posthog/brand/fonts'
import cursorHogUrl from '@posthog/brand/hoggies/png/cursor'
import { Logo } from '@posthog/brand/logo'

import { PANEL_STATES } from './panelStates.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.join(HERE, 'images')
const extensionDir = path.resolve(process.argv[2] ?? path.join(HERE, '../../../../dist/toolbar-extension/chrome'))
const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'toolbar-store-listing-'))

// Site captures of an invented website, taken with the built extension and the PostHog API mocked. Each one is
// 1681x864 points at 2x: a 44-point browser bar, the site, then a 401-point side panel that the screenshots replace
// with a fresh render of the current panel.
const PR_ASSETS = 'https://raw.githubusercontent.com/PostHog/pr-assets'
const SCREENSHOTS = [
    {
        file: 'screenshot-1-heatmaps.png',
        tool: 'heatmap',
        capture: `${PR_ASSETS}/27e0f0f7e953a1b8e4dc0cf1e36f8616dfcbce6a/2026/10/798494be-3d08-4f27-8098-a82a7fd43968.png`,
        title: 'See where people click',
        subtitle: 'Heatmaps, clickmaps and scroll depth on your live site',
    },
    {
        file: 'screenshot-2-inspect.png',
        tool: 'inspect',
        capture: `${PR_ASSETS}/521bc21aa47401892fba163deb1b8e2cfb047340/2026/10/91795ef3-5229-4fc3-b24e-10631d9b4fb3.png`,
        title: 'Inspect any element',
        subtitle: 'See its selector, clicks and actions, then create an action from it',
    },
    {
        file: 'screenshot-3-feature-flags.png',
        tool: 'flags',
        capture: `${PR_ASSETS}/08f1b71ce12c27f330166e11428a02abfa9caa30/2026/10/15f8cb5d-9725-409f-994d-53e2e57627d1.png`,
        title: 'Override feature flags on the page',
        subtitle: 'Try each variant and payload in your browser without changing code',
    },
    {
        file: 'screenshot-4-events.png',
        tool: 'events',
        capture: `${PR_ASSETS}/02038f1dc6c53b4e6335a458096049efba8d98c6/2026/10/a65dd337-f722-48bf-96f8-66ad4d28427d.png`,
        title: 'Watch events as they happen',
        subtitle: 'Check every event and property posthog-js sends from the page',
    },
    {
        file: 'screenshot-5-experiments.png',
        tool: 'experiments',
        capture: `${PR_ASSETS}/5032a99804a861bade3e77e0df2299d1027fe48e/2026/10/f92228c9-3e47-4f2a-b0fd-586dce8f5629.png`,
        title: 'Build no-code experiments',
        subtitle: 'Edit a variant and preview it on the page before you launch',
    },
]
const CAPTURE = { width: 1681, siteWidth: 1279, barHeight: 44 }
const PANEL = { width: 400, height: 820 }

const TILE_COLOR = '#ff5c1c'
const TILE_TAGLINE = 'Toolbar in<br>a side panel'
const TILES = [
    {
        file: 'small-promo-tile.png',
        width: 440,
        height: 280,
        logo: 190,
        tagline: 30,
        hog: 250,
        hogRight: -18,
        hogBottom: -24,
        padLeft: 30,
    },
    {
        file: 'marquee-promo-tile.png',
        width: 1400,
        height: 560,
        logo: 420,
        tagline: 66,
        hog: 560,
        hogRight: 230,
        hogBottom: -40,
        padLeft: 150,
    },
]

// The site and the panel share one scale, so the window reads as one real browser window.
const SCREEN = { width: 1280, height: 800, margin: 49, barHeight: 34 }
const SCALE = (SCREEN.width - 2 * SCREEN.margin) / (CAPTURE.siteWidth + PANEL.width)
const SITE_WIDTH = CAPTURE.siteWidth * SCALE
const PANEL_WIDTH = PANEL.width * SCALE
const CONTENT_HEIGHT = PANEL.height * SCALE
const WINDOW_TOP = SCREEN.height - SCREEN.barHeight - CONTENT_HEIGHT

const UI_HOST = 'https://us.posthog.com'
const TEAM = { id: 1, project_id: 1, name: 'Trailmark website' }
const USER = {
    uuid: '0192f0e4-0000-7000-8000-000000000001',
    distinct_id: 'jane-example',
    email: 'jane@example.com',
    first_name: 'Jane',
    team: TEAM,
    organization: { id: 'org-1', name: 'Trailmark', teams: [TEAM] },
}
const MIME_TYPES = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
}

/** Runs in the panel page before its scripts. Mirrors components/panel/__mocks__/fakeExtensionBrowser.ts. */
function installFakeBrowser({ state, uiHost }) {
    const fakeEvent = () => ({ addListener() {}, removeListener() {} })
    const storage = {
        posthogUiHost: uiHost,
        posthogToolbarTokens: { [`${uiHost}|1`]: { accessToken: 'pha_fake', refreshToken: null, clientId: 'fake' } },
    }
    const fakePort = () => {
        const listeners = []
        const send = (message) => setTimeout(() => listeners.forEach((listener) => listener(message)))
        return {
            name: 'posthog-toolbar-page',
            postMessage(message) {
                if (message?.type === 'start') {
                    send({ type: 'state', state })
                }
            },
            disconnect() {},
            onMessage: { addListener: (listener) => listeners.push(listener), removeListener() {} },
            onDisconnect: fakeEvent(),
        }
    }
    globalThis.browser = {
        tabs: {
            query: async () => [{ id: 1, url: 'https://www.example.com/' }],
            create: async () => ({ id: 2 }),
            remove: async () => undefined,
            connect: fakePort,
            sendMessage: async () => true,
            onActivated: fakeEvent(),
            onRemoved: fakeEvent(),
            onUpdated: fakeEvent(),
        },
        windows: { getCurrent: async () => ({ id: 1 }) },
        storage: {
            local: {
                get: async (key) => ({ [key]: storage[key] }),
                set: async (items) => Object.assign(storage, items),
            },
        },
        scripting: { executeScript: async () => [{}] },
        runtime: { onMessage: fakeEvent(), onConnect: fakeEvent(), getURL: (file) => `/${file}` },
        permissions: {
            contains: async () => true,
            request: async () => true,
            getAll: async () => ({ origins: [] }),
            onAdded: fakeEvent(),
            onRemoved: fakeEvent(),
        },
        action: { onClicked: fakeEvent() },
    }
}

async function renderPanel(browser, tool) {
    const context = await browser.newContext({
        viewport: { width: PANEL.width, height: PANEL.height },
        deviceScaleFactor: 2,
        colorScheme: 'light',
    })
    await context.route('**/*', async (route) => {
        const url = new URL(route.request().url())
        if (url.host === 'extension.test') {
            const file = path.join(extensionDir, decodeURIComponent(url.pathname))
            return fs.existsSync(file)
                ? route.fulfill({ body: fs.readFileSync(file), contentType: MIME_TYPES[path.extname(file)] })
                : route.fulfill({ status: 404 })
        }
        if (url.origin === UI_HOST && url.pathname.startsWith('/api/users/@me')) {
            return route.fulfill({ json: USER })
        }
        if (url.origin === UI_HOST && url.pathname.includes('toolbar_entitlements')) {
            return route.fulfill({ json: { entitlements: { toolbar_heatmaps: true } } })
        }
        if (url.origin === UI_HOST && url.pathname.startsWith('/api/organizations/')) {
            return route.fulfill({ json: { app_urls: ['https://www.example.com'], data_attributes: ['data-attr'] } })
        }
        return route.fulfill({ json: {} })
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.addInitScript(installFakeBrowser, { state: PANEL_STATES[tool], uiHost: UI_HOST })
    await page.goto('http://extension.test/panel.html')
    await page.waitForLoadState('networkidle')
    const file = path.join(workDir, `panel-${tool}.png`)
    await page.screenshot({ path: file })
    await context.close()
    if (errors.length) {
        throw new Error(`The ${tool} panel threw: ${errors.join('; ')}`)
    }
    return file
}

async function downloadCapture(url, tool) {
    const response = await fetch(url)
    if (!response.ok) {
        throw new Error(`Could not download the ${tool} capture: ${response.status} ${url}`)
    }
    const file = path.join(workDir, `capture-${tool}.png`)
    fs.writeFileSync(file, Buffer.from(await response.arrayBuffer()))
    return file
}

const fileUrl = (file) => pathToFileURL(file).href
const svg = (props) =>
    renderToStaticMarkup(createElement(Logo, { ...props, style: { display: 'block', width: '100%' } }))
const baseCss = `
@font-face { font-family: RoundHog; font-weight: 500; src: url(${roundHogMediumUrl}) format('woff2'); }
@font-face { font-family: RoundHog; font-weight: 700; src: url(${roundHogBoldUrl}) format('woff2'); }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: RoundHog, sans-serif; -webkit-font-smoothing: antialiased; position: relative; overflow: hidden; }
`

function screenshotHtml({ title, subtitle, captureFile, panelFile }) {
    return `<!doctype html><html><head><style>${baseCss}
body { width: ${SCREEN.width}px; height: ${SCREEN.height}px; background: #eeefe9; }
.copy { position: absolute; inset: 0 0 auto; height: ${WINDOW_TOP}px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding-bottom: 6px; }
h1 { font-size: 46px; font-weight: 700; color: #151515; letter-spacing: -0.5px; }
p { font-size: 22px; font-weight: 500; color: #5b5d55; }
.window { position: absolute; left: ${SCREEN.margin}px; top: ${WINDOW_TOP}px; width: ${SITE_WIDTH + PANEL_WIDTH + 2}px; height: ${SCREEN.barHeight + CONTENT_HEIGHT + 20}px; border: 1px solid #c9cbc2; border-radius: 12px 12px 0 0; overflow: hidden; background: #fff; box-shadow: 0 18px 48px rgba(40, 42, 35, 0.18), 0 2px 6px rgba(40, 42, 35, 0.08); }
.bar { height: ${SCREEN.barHeight}px; background: #e3e4dd; display: flex; align-items: center; gap: 7px; padding: 0 14px; border-bottom: 1px solid #d3d4cc; }
.dot { width: 11px; height: 11px; border-radius: 50%; }
.url { margin-left: 14px; height: 22px; width: 520px; border-radius: 11px; background: #fff; font: 500 12px -apple-system, 'Helvetica Neue', sans-serif; color: #44463f; display: flex; align-items: center; padding: 0 12px; }
.extension-icon { margin-left: auto; width: 34px; }
.content { display: flex; }
.site { width: ${SITE_WIDTH}px; height: ${CONTENT_HEIGHT}px; overflow: hidden; }
.site img { display: block; width: ${CAPTURE.width * SCALE}px; margin-top: ${-CAPTURE.barHeight * SCALE}px; }
.panel { display: block; width: ${PANEL_WIDTH}px; height: ${CONTENT_HEIGHT}px; border-left: 1px solid #d3d4cc; }
</style></head><body>
<div class="copy"><h1>${title}</h1><p>${subtitle}</p></div>
<div class="window">
  <div class="bar">
    <span class="dot" style="background: #ff5f57"></span><span class="dot" style="background: #febc2e"></span><span class="dot" style="background: #28c840"></span>
    <span class="url">https://www.example.com</span>
    <span class="extension-icon">${svg({ layout: 'logomark' })}</span>
  </div>
  <div class="content">
    <div class="site"><img src="${fileUrl(captureFile)}"></div>
    <img class="panel" src="${fileUrl(panelFile)}">
  </div>
</div>
</body></html>`
}

// Google asks for saturated full-bleed color, little text, and a tile that still reads at half size.
function tileHtml(tile) {
    return `<!doctype html><html><head><style>${baseCss}
body { width: ${tile.width}px; height: ${tile.height}px; background: ${TILE_COLOR}; }
.copy { position: absolute; left: ${tile.padLeft}px; top: 0; bottom: 0; display: flex; flex-direction: column; justify-content: center; gap: ${Math.round(tile.tagline * 0.55)}px; }
.logo { width: ${tile.logo}px; }
.tagline { font-size: ${tile.tagline}px; font-weight: 700; color: #fff; line-height: 1.12; letter-spacing: -0.3px; }
.hog { position: absolute; right: ${tile.hogRight}px; bottom: ${tile.hogBottom}px; width: ${tile.hog}px; height: ${tile.hog}px; }
</style></head><body>
<div class="copy"><div class="logo">${svg({ variant: 'mono', color: '#fff' })}</div><div class="tagline">${TILE_TAGLINE}</div></div>
<img class="hog" src="${cursorHogUrl}">
</body></html>`
}

async function capture(browser, { html, width, height, file }) {
    // The store wants exact sizes in 24-bit PNG without alpha, which is what a Chromium screenshot at 1x gives.
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 })
    const htmlFile = path.join(workDir, `${path.basename(file, '.png')}.html`)
    fs.writeFileSync(htmlFile, html)
    await page.goto(fileUrl(htmlFile))
    await page.evaluate(() => document.fonts.ready)
    await page.waitForLoadState('networkidle')
    await page.screenshot({ path: path.join(OUT_DIR, file) })
    await page.close()
    console.info(`Wrote ${path.relative(process.cwd(), path.join(OUT_DIR, file))}`)
}

if (!fs.existsSync(path.join(extensionDir, 'panel.html'))) {
    throw new Error(`No built extension in ${extensionDir}. Run "pnpm build:toolbar-extension" in frontend/ first.`)
}
fs.mkdirSync(OUT_DIR, { recursive: true })
const browser = await chromium.launch()
try {
    for (const screenshot of SCREENSHOTS) {
        const [captureFile, panelFile] = await Promise.all([
            downloadCapture(screenshot.capture, screenshot.tool),
            renderPanel(browser, screenshot.tool),
        ])
        await capture(browser, {
            html: screenshotHtml({ ...screenshot, captureFile, panelFile }),
            width: SCREEN.width,
            height: SCREEN.height,
            file: screenshot.file,
        })
    }
    for (const tile of TILES) {
        await capture(browser, { html: tileHtml(tile), width: tile.width, height: tile.height, file: tile.file })
    }
} finally {
    await browser.close()
    fs.rmSync(workDir, { recursive: true, force: true })
}
