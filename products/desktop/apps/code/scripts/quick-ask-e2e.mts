import { readFileSync } from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { AuthService } from "@posthog/core/auth/auth";
import { QuickAskService } from "@posthog/quick-ask/service/quick-ask";
import {
  REPLAY_FOLLOW_UP,
  REPLAY_FOLLOW_UP_ANSWER,
  REPLAY_FOLLOW_UP_PRELUDE,
  REPLAY_QUESTION,
  REPLAY_STRAY_ANSWER,
  startReplayServer,
} from "@posthog/quick-ask/service/replay-fixture";
import { chromium } from "playwright-core";

/**
 * The whole quick-ask pipeline: the real QuickAskService asks a replay of a
 * production run's tasks API and stream, and its events drive the built panel
 * in headless Chromium through the real input. Asserts the rendered DOM.
 *
 * Run from apps/code after `pnpm compile`: `pnpm e2e:quick-ask`.
 */

const rendererDir = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "../.vite/renderer/main_window",
);

const MIME: Record<string, string> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
};

function serveRenderer(): Promise<{ origin: string; close: () => void }> {
  const server = http.createServer((request, response) => {
    const file = path.join(rendererDir, (request.url ?? "/").split("?")[0]);
    try {
      const body = readFileSync(file);
      response.writeHead(200, {
        "Content-Type": MIME[path.extname(file)] ?? "application/octet-stream",
      });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as AddressInfo;
      resolve({
        origin: `http://127.0.0.1:${port}`,
        close: () => server.close(),
      });
    });
  });
}

function fail(message: string): never {
  console.error(`✗ ${message}`);
  process.exit(1);
}

function pass(message: string): void {
  console.log(`✓ ${message}`);
}

const replay = await startReplayServer();
const renderer = await serveRenderer();

const auth = {
  getValidAccessToken: async () => ({
    accessToken: "t",
    apiHost: replay.origin,
  }),
  getState: () => ({ currentProjectId: 2 }),
  authenticatedFetch: (
    fetchImpl: typeof fetch,
    url: string,
    init: RequestInit,
  ) => fetchImpl(url, init),
} as unknown as AuthService;
const service = new QuickAskService(auth);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 700, height: 900 } });
const pageErrors: string[] = [];
page.on("pageerror", (error) => pageErrors.push(error.message));

// The panel's preload bridges, stubbed: tRPC absorbs requests (chart cards
// stay in their loading state without a session), and quickAsk.ask routes to
// the real service in this process.
// A capture in this harness attaches a canned PNG; the real annotator UI is
// exercised separately below.
const SHOT_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
let pendingShot: { name: string; base64: string; mimeType: string } | null =
  null;
await page.exposeFunction(
  "__hostAsk",
  (question: string, conversationId?: string) => {
    const attachments = pendingShot ? [pendingShot] : [];
    pendingShot = null;
    void page.evaluate("window.__qaAttach({ previewDataUrl: null })");
    void (async () => {
      for await (const event of service.ask({
        question,
        conversationId,
        attachments,
      })) {
        await page.evaluate(`window.__qaEmit(${JSON.stringify(event)})`);
      }
    })();
  },
);
await page.exposeFunction("__hostCapture", () => {
  pendingShot = {
    name: "screenshot.png",
    base64: SHOT_BASE64,
    mimeType: "image/png",
  };
  void page.evaluate(
    `window.__qaAttach({ previewDataUrl: "data:image/png;base64,${SHOT_BASE64}" })`,
  );
});
await page.exposeFunction("__hostDiscard", () => {
  pendingShot = null;
});
// The panel's chart cards resolve data through the authenticated client,
// which forms from auth state served over the tRPC bridge. Stub the bridge
// wire protocol so the real client forms, and intercept its API calls below.
// A string, not a function: tsx's esbuild transform injects helpers that do
// not exist inside the page.
await page.addInitScript(`
  window.electronTRPC = {
    handlers: [],
    sendMessage(message) {
      if (message.method !== "request") return;
      const { id, type, path } = message.operation;
      if (type === "subscription") return;
      const respond = (data) => {
        for (const handler of window.electronTRPC.handlers) {
          handler({ id, result: { type: "data", data: { json: data } } });
        }
      };
      if (path === "auth.getState") {
        respond({
          status: "authenticated",
          bootstrapComplete: true,
          cloudRegion: "us",
          orgProjectsMap: {},
          currentOrgId: "org-1",
          currentProjectId: 2,
          desktopAccess: { projectId: 2, status: "allowed", reason: null },
          needsScopeReauth: false,
          sessionType: "desktop",
          sessionExpiresAt: null,
          sessionEndReason: null,
        });
      } else if (path === "auth.getValidAccessToken") {
        respond({ accessToken: "e2e-token", apiHost: "https://us.posthog.com" });
      } else {
        respond({});
      }
    },
    onMessage(callback) {
      window.electronTRPC.handlers.push(callback);
    },
  };
  const listeners = [];
  const attachListeners = [];
  window.__qaEmit = (event) => { for (const listener of listeners) listener(event); };
  window.__qaAttach = (payload) => { for (const listener of attachListeners) listener(payload); };
  window.quickAsk = {
    hide: () => { window.__qaHides = (window.__qaHides ?? 0) + 1; },
    resize: () => {},
    openInApp: () => {},
    dragStart: () => {},
    dragEnd: () => {},
    ask: (question, conversationId) => window.__hostAsk(question, conversationId),
    cancel: () => {},
    reset: () => {},
    onEvent: (callback) => { listeners.push(callback); return () => {}; },
    onLayout: () => () => {},
    onShown: () => () => {},
    onShake: (cb) => { window.__qaShake = cb; return () => { window.__qaShake = undefined; }; },
    capture: () => window.__hostCapture(),
    discardAttachment: () => window.__hostDiscard(),
    onAttachment: (callback) => { attachListeners.push(callback); return () => {}; },
    openScreenSettings: () => { window.__qaSettingsOpens = (window.__qaSettingsOpens ?? 0) + 1; },
  };
`);

// The chart card's live query, canned: a date-keyed grid that shapes into a
// line chart.
await page.route("https://us.posthog.com/**", async (route) => {
  if (route.request().url().includes("/query/")) {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        columns: ["day", "count()"],
        results: [
          ["2026-08-08", 34000],
          ["2026-08-09", 48000],
          ["2026-08-10", 86000],
          ["2026-08-11", 84000],
          ["2026-08-12", 82000],
          ["2026-08-13", 79000],
          ["2026-08-14", 68000],
        ],
      }),
    });
    return;
  }
  await route.fulfill({ status: 404, body: "" });
});

await page.goto(`${renderer.origin}/quick-ask.html`);
await page.waitForSelector(".qa-pill input", { timeout: 15_000 });
pass("panel booted");

await service.warm();
pass("sandbox warmed");

// First question through the real input.
await page.fill(".qa-pill input", REPLAY_QUESTION);
await page.press(".qa-pill input", "Enter");
await page.waitForSelector(".qa-actions", { timeout: 15_000 });
const focused = (await page.evaluate(
  'document.activeElement === document.querySelector(".qa-pill input")',
)) as boolean;
if (!focused) {
  fail("input did not regain focus after the answer");
}

const answer = (await page.evaluate(
  'document.querySelector(".qa-answer")?.textContent ?? ""',
)) as string;
if (!answer.includes("Signups held steady this week")) {
  fail(`answer text not rendered: ${JSON.stringify(answer.slice(0, 200))}`);
}
if (answer.includes(REPLAY_STRAY_ANSWER)) {
  fail("description-turn output leaked into the panel");
}
if (/<\/?hogql/.test(answer)) {
  fail("raw object tag leaked into the rendered answer");
}
const chip = (await page.evaluate(
  'document.querySelector(".qa-answer .qa-ref")?.textContent ?? ""',
)) as string;
if (!chip.includes("Tuesday spike")) {
  fail(`inline tag did not render as a chip: ${JSON.stringify(chip)}`);
}
pass("answer rendered, inline tag is a chip, stray turn skipped, no raw tags");

await page.waitForSelector(".qa-chart .qa-chart-svg path", { timeout: 15_000 });
const chartTitle = (await page.evaluate(
  'document.querySelector(".qa-chart .qa-chart-title")?.textContent ?? ""',
)) as string;
if (chartTitle !== "Signups per day, last 7 days") {
  fail(`chart card missing or mistitled: ${JSON.stringify(chartTitle)}`);
}
const stat = (await page.evaluate(
  'document.querySelector(".qa-chart-stat-value")?.textContent ?? ""',
)) as string;
if (!stat) {
  fail("chart headline stat missing");
}
pass(`hogql block tag drew the compact chart (latest ${stat})`);

// Hovering a chip mounts the live preview card.
await page.hover(".qa-answer .qa-ref");
await page.waitForSelector("[data-testid=evidence-hover-card]", {
  timeout: 5_000,
});
// The card is styled by layered Tailwind utilities; an unscoped panel reset
// would flatten its padding and surface to nothing.
const cardStyle = (await page.evaluate(`(() => {
  const wrapper = document.querySelector("[data-testid=evidence-hover-card]");
  const card = wrapper?.querySelector(".w-80");
  const surface = card?.parentElement ? getComputedStyle(card.parentElement) : null;
  return {
    padding: card ? getComputedStyle(card).paddingTop : "",
    background: surface?.backgroundColor ?? "",
  };
})()`)) as { padding: string; background: string };
if (!cardStyle.padding || cardStyle.padding === "0px") {
  fail(
    `hover card lost its padding (padding-top: ${cardStyle.padding || "none"})`,
  );
}
if (!cardStyle.background || cardStyle.background === "rgba(0, 0, 0, 0)") {
  fail(`hover card surface is transparent (${cardStyle.background || "none"})`);
}
pass(
  `chip hover mounts the preview card (padding ${cardStyle.padding}, solid surface)`,
);

// The close button hides the panel; clicking elsewhere must not.
await page.click(".qa-close");
const hides = (await page.evaluate("window.__qaHides ?? 0")) as number;
if (hides !== 1) {
  fail(`close button did not hide the panel (hides: ${hides})`);
}
pass("close button hides the panel");

// Shaking the panel (relayed from the main-process drag loop) cycles the hedgehog.
const hogBefore = (await page.evaluate(
  'document.querySelector(".qa-hog img")?.getAttribute("src") ?? ""',
)) as string;
await page.evaluate("window.__qaShake?.()");
await page
  .waitForFunction(
    `document.querySelector(".qa-hog img")?.getAttribute("src") !== ${JSON.stringify(hogBefore)}`,
    undefined,
    { timeout: 2_000 },
  )
  .catch(() => {});
const hogAfter = (await page.evaluate(
  'document.querySelector(".qa-hog img")?.getAttribute("src") ?? ""',
)) as string;
if (!hogBefore || hogBefore === hogAfter) {
  fail("shaking did not change the hedgehog");
}
pass("shake cycles the hedgehog");

// Double-clicking the hedgehog collapses to mini mode: hedgehog + status dot.
await page.dblclick(".qa-hog");
const miniState = (await page.evaluate(`(() => {
  const pill = document.querySelector(".qa-pill");
  const card = document.querySelector(".qa-card");
  const dot = document.querySelector(".qa-status");
  return {
    pillHidden: !pill || getComputedStyle(pill).display === "none",
    cardHidden: !card || getComputedStyle(card).display === "none",
    dotVisible: !!dot && getComputedStyle(dot).display !== "none",
    dotStatus: dot?.className ?? "",
  };
})()`)) as {
  pillHidden: boolean;
  cardHidden: boolean;
  dotVisible: boolean;
  dotStatus: string;
};
if (!miniState.pillHidden || !miniState.cardHidden) {
  fail("mini mode did not hide the pill and answer");
}
if (!miniState.dotVisible || !miniState.dotStatus.includes("qa-status-ready")) {
  fail(`mini mode status dot wrong (${miniState.dotStatus || "missing"})`);
}
// Double-click again restores the panel and refocuses the input.
await page.dblclick(".qa-hog");
await page.waitForSelector(".qa-pill input", { timeout: 2_000 });
await page
  .waitForFunction(
    'document.activeElement === document.querySelector(".qa-pill input")',
    undefined,
    { timeout: 2_000 },
  )
  .catch(() => {});
const restored = (await page.evaluate(
  'document.activeElement === document.querySelector(".qa-pill input")',
)) as boolean;
if (!restored) {
  fail("leaving mini mode did not refocus the input");
}
pass("double-click toggles mini mode with a status dot");

// A long shake summons hogzilla and takes the panel hostage; another long
// shake calms it back down.
await page.waitForTimeout(1_600); // separate from the single-shake streak
for (let i = 0; i < 5; i++) {
  await page.evaluate("window.__qaShake?.()");
}
await page.waitForSelector(".qa-zilla", { timeout: 2_000 });
const zilla = (await page.evaluate(`(() => {
  const pill = document.querySelector(".qa-pill");
  const img = document.querySelector(".qa-hog img");
  return {
    pillHidden: !pill || getComputedStyle(pill).display === "none",
    src: img?.getAttribute("src") ?? "",
  };
})()`)) as { pillHidden: boolean; src: string };
if (!zilla.pillHidden) {
  fail("hogzilla left the pill usable");
}
if (!zilla.src.includes("hogzilla")) {
  fail(`hogzilla shows the wrong avatar (${zilla.src})`);
}
await page.waitForTimeout(1_600);
for (let i = 0; i < 5; i++) {
  await page.evaluate("window.__qaShake?.()");
}
await page.waitForSelector(".qa-zilla", { state: "detached", timeout: 2_000 });
await page.waitForSelector(".qa-pill input", { timeout: 2_000 });
pass("long shake summons hogzilla, another long shake calms it");

if (process.env.QUICK_ASK_E2E_METRICS) {
  const metrics = await page.evaluate(`(() => {
    const rect = (selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { w: Math.round(r.width), h: Math.round(r.height), font: cs.fontSize, mt: cs.marginTop, mb: cs.marginBottom, pad: cs.padding };
    };
    return JSON.stringify({
      card: rect(".qa-card"),
      answer: rect(".qa-answer"),
      chart: rect(".qa-chart"),
      chartSvg: rect(".qa-chart-svg"),
      chartTitle: rect(".qa-chart-title"),
      stat: rect(".qa-chart-stat-value"),
      text: rect(".qa-answer .rt-Text"),
      code: rect(".qa-answer .rt-Code"),
      chip: rect(".qa-ref"),
      labels: rect(".qa-chart-labels"),
    }, null, 1);
  })()`);
  console.log("metrics:", metrics);
}

const shot = process.env.QUICK_ASK_E2E_SCREENSHOT;
if (shot) {
  const box = await page.locator(".qa-root").boundingBox();
  if (box) await page.screenshot({ path: shot, clip: box });
  pass(`screenshot written to ${shot}`);
}

// Capture attaches a screenshot chip; remove discards it; a second capture
// rides the follow-up.
// A denied capture surfaces the permission error with a settings link.
await page.evaluate(
  'window.__qaAttach({ previewDataUrl: null, error: "PostHog needs screen recording permission.", canOpenSettings: true })',
);
await page.waitForSelector(".qa-attach-settings", { timeout: 5_000 });
await page.click(".qa-attach-settings");
await page.waitForSelector(".qa-attach", { state: "detached", timeout: 5_000 });
if (((await page.evaluate("window.__qaSettingsOpens")) as number) !== 1) {
  fail("settings link did not reach the bridge");
}
pass("permission error offers the settings link");

await page.click(".qa-shot");
await page.waitForSelector(".qa-attach img", { timeout: 5_000 });
await page.click('.qa-attach button[aria-label="Remove screenshot"]');
await page.waitForSelector(".qa-attach", { state: "detached", timeout: 5_000 });
if (pendingShot !== null) {
  fail("removing the chip did not discard the pending screenshot");
}
await page.click(".qa-shot");
await page.waitForSelector(".qa-attach img", { timeout: 5_000 });
pass("screenshot chip attaches and removes");

// Follow-up through the same input.
await page.fill(".qa-pill input", REPLAY_FOLLOW_UP);
await page.press(".qa-pill input", "Enter");
await page.waitForFunction(
  `document.querySelector(".qa-answer")?.textContent?.includes(${JSON.stringify(REPLAY_FOLLOW_UP_ANSWER)})`,
  undefined,
  { timeout: 15_000 },
);
pass("follow-up answer rendered");

await page.waitForSelector(".qa-attach", { state: "detached", timeout: 5_000 });
const prepare = replay.requests.find((r) =>
  r.path.endsWith("/prepare_upload/"),
);
if (!prepare || !prepare.path.includes("/runs/run-1/artifacts/")) {
  fail(`screenshot was not uploaded to the live run: ${prepare?.path}`);
}
const userMessage = replay.requests.find(
  (r) => (r.body as { method?: string } | null)?.method === "user_message",
);
const artifactIds = (
  userMessage?.body as { params?: { artifact_ids?: string[] } }
).params?.artifact_ids;
if (JSON.stringify(artifactIds) !== '["art-1"]') {
  fail(
    `follow-up did not reference the artifact: ${JSON.stringify(artifactIds)}`,
  );
}
pass("screenshot uploaded and referenced on the follow-up");

// The follow-up turn has text on both sides of a tool call, so the answer
// arrives as two segments with a pager pinned to the top of the card.
await page.waitForSelector(".qa-actions", { timeout: 15_000 });
await page.waitForSelector(".qa-status-row .qa-pager", { timeout: 5_000 });
// Let the card's mount animation finish so bounding boxes are stable.
await page.waitForTimeout(400);
const pagerBefore = await page
  .locator(".qa-status-row .qa-pager")
  .boundingBox();
await page.click('.qa-pager button[aria-label="Previous part"]');
await page.waitForFunction(
  `document.querySelector(".qa-answer")?.textContent?.includes(${JSON.stringify(REPLAY_FOLLOW_UP_PRELUDE)})`,
  undefined,
  { timeout: 5_000 },
);
const pagerAfter = await page.locator(".qa-status-row .qa-pager").boundingBox();
if (!pagerBefore || !pagerAfter || pagerBefore.y !== pagerAfter.y) {
  throw new Error(
    `pager moved while paging: ${pagerBefore?.y} -> ${pagerAfter?.y}`,
  );
}
if (
  await page
    .locator(".qa-actions")
    .textContent()
    .then((t) => t?.includes("PostHog AI"))
) {
  throw new Error("source label still present in the actions row");
}
await page.click('.qa-pager button[aria-label="Next part"]');
pass("segment pager pages back without moving");

// New chat clears the thread and hands focus back to the input.
await page.click(".qa-new");
await page.waitForSelector(".qa-card", { state: "detached", timeout: 5_000 });
// Focus returns on the next frame after the re-render.
await page
  .waitForFunction(
    'document.activeElement === document.querySelector(".qa-pill input")',
    undefined,
    { timeout: 2_000 },
  )
  .catch(() => {});
const focusedAfterReset = (await page.evaluate(
  'document.activeElement === document.querySelector(".qa-pill input")',
)) as boolean;
if (!focusedAfterReset) {
  fail("input not focused after new chat");
}
pass("new chat clears the thread and focuses the input");

// An empty, untouched panel folds into mini mode; a draft keeps it open.
await page.goto(`${renderer.origin}/quick-ask.html?idleCollapse=400`);
await page.waitForSelector(".qa-pill input", { timeout: 15_000 });
await page.waitForSelector(".qa-mini", { timeout: 3_000 });
await page.goto(`${renderer.origin}/quick-ask.html?idleCollapse=400`);
await page.waitForSelector(".qa-pill input", { timeout: 15_000 });
await page.fill(".qa-pill input", "still typing");
await page.waitForTimeout(900);
if (await page.locator(".qa-mini").count()) {
  fail("panel collapsed while a draft was in the input");
}
pass("empty idle panel folds into mini mode, drafts keep it open");

// The panel follows the app theme; the system scheme flips the palette live.
await page.emulateMedia({ colorScheme: "dark" });
await page.waitForFunction(
  'document.documentElement.classList.contains("dark")',
  undefined,
  { timeout: 2_000 },
);
const darkPill = (await page.evaluate(
  'getComputedStyle(document.querySelector(".qa-pill")).backgroundColor',
)) as string;
await page.emulateMedia({ colorScheme: "light" });
await page.waitForFunction(
  '!document.documentElement.classList.contains("dark")',
  undefined,
  { timeout: 2_000 },
);
const lightPill = (await page.evaluate(
  'getComputedStyle(document.querySelector(".qa-pill")).backgroundColor',
)) as string;
if (!darkPill || darkPill === lightPill) {
  fail(`theme change did not restyle the pill (${darkPill} vs ${lightPill})`);
}
pass("panel palette follows the theme");

if (pageErrors.length > 0) {
  fail(`page errors: ${pageErrors.join(" | ")}`);
}
pass("no page errors");

// The annotator app: crop by drag, ink an arrow, export the flattened PNG.
const annotate = await browser.newPage({
  viewport: { width: 1200, height: 800 },
});
const annotateErrors: string[] = [];
annotate.on("pageerror", (error) => annotateErrors.push(error.message));
await annotate.addInitScript(`
  window.quickAskAnnotate = {
    shot: async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 2400;
      canvas.height = 1600;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#1d4ed8";
      ctx.fillRect(0, 0, 2400, 1600);
      return canvas.toDataURL("image/png");
    },
    done: (dataUrl) => { window.__annotated = dataUrl; },
    cancel: () => { window.__cancelled = true; },
  };
`);
await annotate.goto(`${renderer.origin}/quick-ask-annotate.html`);
await annotate.waitForSelector(".an-shot", { timeout: 15_000 });

// The whole screen is selected from the start; the toolbar is up
// immediately and no selection is forced.
await annotate.waitForSelector(".an-toolbar", { timeout: 15_000 });
const fullDims = await annotate.locator(".an-size").textContent();
if (fullDims?.trim() !== "2400 × 1600") {
  fail(`initial dimension label reads "${fullDims}", expected full screen`);
}

// Crop via the toolbar tool: 300x200 at (100, 100). The shot is 2x the
// viewport, so the dimension label reads export pixels.
await annotate.click('[aria-label="Crop (C)"]');
await annotate.waitForSelector(".an-hint", { timeout: 5_000 });
await annotate.mouse.move(100, 100);
await annotate.mouse.down();
await annotate.mouse.move(400, 300, { steps: 5 });
await annotate.mouse.up();
// The toolbar is pinned to the top of the screen, away from the selection.
const toolbarBox = await annotate.locator(".an-toolbar").boundingBox();
if (!toolbarBox || toolbarBox.y > 40) {
  fail(`toolbar sits at y=${toolbarBox?.y}, expected the top of the screen`);
}
const dims = await annotate.locator(".an-size").textContent();
if (dims?.trim() !== "600 × 400") {
  fail(`dimension label reads "${dims}", expected "600 × 400"`);
}

// Grow the selection by its south-east handle; the label follows.
await annotate.mouse.move(400, 300);
await annotate.mouse.down();
await annotate.mouse.move(450, 350, { steps: 5 });
await annotate.mouse.up();
const grown = await annotate.locator(".an-size").textContent();
if (grown?.trim() !== "700 × 500") {
  fail(`dimension label reads "${grown}" after resize, expected "700 × 500"`);
}

// Ink: an arrow, a text label, and a pixelated region.
await annotate.click('[aria-label="Arrow (A)"]');
await annotate.mouse.move(150, 150);
await annotate.mouse.down();
await annotate.mouse.move(320, 240, { steps: 5 });
await annotate.mouse.up();

await annotate.click('[aria-label="Text (T)"]');
// The text tool opens its options row, and the editor previews the
// default background exactly as it exports.
await annotate.waitForSelector(".an-subbar", { timeout: 5_000 });
await annotate.mouse.click(200, 180);
await annotate.waitForSelector(".an-text-input.an-text-solid", {
  timeout: 5_000,
});
await annotate.keyboard.type("LGTM");
await annotate.keyboard.press("Enter");
// The editor commits into a shape; a lost focus race would leave it open.
await annotate.waitForSelector(".an-text-input", {
  state: "detached",
  timeout: 5_000,
});

await annotate.click('[aria-label="Pixelate (X)"]');
await annotate.mouse.move(250, 210);
await annotate.mouse.down();
await annotate.mouse.move(340, 270, { steps: 5 });
await annotate.mouse.up();

// Undo removes the pixelation; redo restores it.
await annotate.click('[aria-label="Undo (⌘Z)"]');
const redoEnabled = await annotate
  .locator('[aria-label="Redo (⇧⌘Z)"]')
  .isEnabled();
if (!redoEnabled) {
  fail("undo did not enable redo");
}
await annotate.click('[aria-label="Redo (⇧⌘Z)"]');

// Counter drops numbered badges; the select tool moves and deletes objects.
await annotate.click('[aria-label="Counter (N)"]');
await annotate.mouse.click(180, 320);
await annotate.mouse.click(220, 320);
await annotate.click('[aria-label="Select (V)"]');
await annotate.mouse.click(220, 320);
await annotate.waitForSelector('[aria-label="Delete (⌫)"]', {
  timeout: 5_000,
});
await annotate.mouse.move(220, 320);
await annotate.mouse.down();
await annotate.mouse.move(262, 332, { steps: 4 });
await annotate.mouse.up();
await annotate.click('[aria-label="Ink #3b82f6"]');
await annotate.click('[aria-label="Delete (⌫)"]');
await annotate.waitForSelector('[aria-label="Delete (⌫)"]', {
  state: "detached",
  timeout: 5_000,
});
pass("counter badges place; select tool moves, recolors, and deletes");

// Arrow endpoints re-aim the line, and boxes resize by their handles;
// drawing hands over the select tool.
await annotate.mouse.click(170, 161); // on the arrow's shaft
await annotate.waitForSelector('[aria-label="Delete (⌫)"]', {
  timeout: 5_000,
});
await annotate.mouse.move(320, 240); // the arrow's tip handle
await annotate.mouse.down();
await annotate.mouse.move(400, 300, { steps: 5 });
await annotate.mouse.up();
const inkAt = async (x: number, y: number): Promise<number> =>
  (await annotate.evaluate(`(() => {
    const ctx = document.querySelector(".an-overlay").getContext("2d");
    return ctx.getImageData(${x}, ${y}, 1, 1).data[3];
  })()`)) as number;
if ((await inkAt(380, 288)) < 128) {
  fail("dragging the arrow tip did not extend the line");
}
await annotate.keyboard.press("r"); // shortcut into the box tool
if ((await inkAt(230, 220)) > 128) {
  fail("box resize probe already inked");
}
await annotate.mouse.move(120, 120);
await annotate.mouse.down();
await annotate.mouse.move(200, 170, { steps: 5 });
await annotate.mouse.up();
const selectAfterDraw = await annotate
  .locator('[aria-label="Select (V)"]')
  .getAttribute("class");
if (!selectAfterDraw?.includes("an-active")) {
  fail("drawing a box did not hand over the select tool");
}
await annotate.mouse.move(200, 170); // the box's south-east handle
await annotate.mouse.down();
await annotate.mouse.move(260, 220, { steps: 5 });
await annotate.mouse.up();
if ((await inkAt(230, 220)) < 128) {
  fail("dragging the box handle did not resize it");
}
pass("arrow tips re-aim, boxes resize, drawing hands over select");

// Text sizing and wrapping: a second label, resized via the options row,
// then narrowed by its side handle until it breaks into two lines.
await annotate.click('[aria-label="Text (T)"]');
await annotate.mouse.click(140, 260);
await annotate.waitForSelector(".an-text-input", { timeout: 5_000 });
await annotate.keyboard.type("wrap me please now");
await annotate.keyboard.press("Enter");
await annotate.waitForSelector(".an-text-input", {
  state: "detached",
  timeout: 5_000,
});
await annotate.click('[aria-label="Select (V)"]');
await annotate.mouse.click(160, 265);
await annotate.waitForSelector('[aria-label="Delete (⌫)"]', {
  timeout: 5_000,
});
const sizeBefore = await annotate.locator(".an-sub-value").textContent();
const slider = await annotate.locator('[aria-label="Text size"]').boundingBox();
if (!slider) {
  fail("text size slider not visible for a selected text object");
} else {
  await annotate.mouse.click(slider.x + slider.width - 2, slider.y + 2);
}
const sizeAfter = await annotate.locator(".an-sub-value").textContent();
if (Number(sizeAfter) <= Number(sizeBefore)) {
  fail(`slider left size at ${sizeAfter}, expected above ${sizeBefore}`);
}
// Undo the size change so the wrap drag starts from known 17px metrics;
// undo drops the selection, so pick the label up again.
await annotate.click('[aria-label="Undo (\u2318Z)"]');
await annotate.mouse.click(160, 265);
await annotate.waitForSelector('[aria-label="Delete (\u232b)"]', {
  timeout: 5_000,
});
const textW = (await annotate.evaluate(`(() => {
  const ctx = document.createElement("canvas").getContext("2d");
  ctx.font = '600 17px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  return ctx.measureText("wrap me please now").width;
})()`)) as number;
// Solid pill ink only; the pill's soft drop shadow does not count.
const probe = async (): Promise<number> =>
  (await annotate.evaluate(`(() => {
    const ctx = document.querySelector(".an-overlay").getContext("2d");
    return ctx.getImageData(150, 295, 1, 1).data[3];
  })()`)) as number;
if ((await probe()) > 128) {
  fail("second text line is inked before the width drag");
}
const edgeX = 140 + textW + 13;
await annotate.mouse.move(edgeX, 271);
await annotate.mouse.down();
await annotate.mouse.move(140 + textW / 2, 271, { steps: 5 });
await annotate.mouse.up();
if ((await probe()) < 128) {
  fail("narrowing the text did not wrap it onto a second line");
}
pass("text options row sizes text; side handle wraps it to multi-line");

// A long line auto-wraps to the room inside the selection, and finishing
// hands over the select tool with the fresh label selected.
await annotate.click('[aria-label="Text (T)"]');
await annotate.mouse.click(140, 305);
await annotate.waitForSelector(".an-text-input", { timeout: 5_000 });
await annotate.keyboard.type(
  "a very long single line that should wrap by itself",
);
await annotate.keyboard.press("Enter");
await annotate.waitForSelector(".an-text-input", {
  state: "detached",
  timeout: 5_000,
});
await annotate.waitForSelector('[aria-label="Delete (⌫)"]', {
  timeout: 5_000,
});
const selectActive = await annotate
  .locator('[aria-label="Select (V)"]')
  .getAttribute("class");
if (!selectActive?.includes("an-active")) {
  fail("finishing a label did not hand over the select tool");
}
const wrapped = (await annotate.evaluate(`(() => {
  const ctx = document.querySelector(".an-overlay").getContext("2d");
  return ctx.getImageData(150, 335, 1, 1).data[3];
})()`)) as number;
if (wrapped < 128) {
  fail("long label did not auto-wrap inside the selection");
}
pass("long labels auto-wrap and finish into the select tool");

await annotate.click(".an-attach");
await annotate.waitForFunction("typeof window.__annotated === 'string'", {
  timeout: 5_000,
});
const exported = (await annotate.evaluate(`
  new Promise((resolve) => {
    const image = new Image();
    image.onload = () =>
      resolve({
        prefix: window.__annotated.slice(0, 22),
        width: image.naturalWidth,
        height: image.naturalHeight,
      });
    image.src = window.__annotated;
  })
`)) as { prefix: string; width: number; height: number };
if (exported.prefix !== "data:image/png;base64,") {
  fail(`annotator exported ${exported.prefix}`);
}
if (exported.width !== 700 || exported.height !== 500) {
  fail(
    `annotator export is ${exported.width}x${exported.height}, expected 700x500`,
  );
}
if (annotateErrors.length > 0) {
  fail(`annotator page errors: ${annotateErrors.join(" | ")}`);
}
pass("annotator crops, resizes, inks arrow/text/pixelate, and exports");

await browser.close();
renderer.close();
await replay.close();
console.log("quick-ask e2e: all checks passed");
