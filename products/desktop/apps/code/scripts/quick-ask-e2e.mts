import { readFileSync } from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import type { AuthService } from "../../../packages/core/src/auth/auth";
import { QuickAskService } from "../../../packages/core/src/quick-ask/quick-ask";
import {
  REPLAY_FOLLOW_UP,
  REPLAY_FOLLOW_UP_ANSWER,
  REPLAY_QUESTION,
  REPLAY_STRAY_ANSWER,
  startReplayServer,
} from "../src/main/quick-ask-replay-fixture";

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
await page.exposeFunction(
  "__hostAsk",
  (question: string, conversationId?: string) => {
    void (async () => {
      for await (const event of service.ask({ question, conversationId })) {
        await page.evaluate(`window.__qaEmit(${JSON.stringify(event)})`);
      }
    })();
  },
);
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
          hasCodeAccess: true,
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
  window.__qaEmit = (event) => { for (const listener of listeners) listener(event); };
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
// The input locks while the answer is in flight.
await page.waitForSelector(".qa-pill input[disabled]", { timeout: 2_000 });
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
await page.waitForSelector("[data-radix-popper-content-wrapper]", {
  timeout: 5_000,
});
pass("chip hover mounts the preview card");

// The close button hides the panel; clicking elsewhere must not.
await page.click(".qa-close");
const hides = (await page.evaluate("window.__qaHides ?? 0")) as number;
if (hides !== 1) {
  fail(`close button did not hide the panel (hides: ${hides})`);
}
pass("close button hides the panel");

// Double-clicking the hedgehog cycles the hedgehog.
const hogBefore = (await page.evaluate(
  'document.querySelector(".qa-hog img")?.getAttribute("src") ?? ""',
)) as string;
await page.dblclick(".qa-hog");
const hogAfter = (await page.evaluate(
  'document.querySelector(".qa-hog img")?.getAttribute("src") ?? ""',
)) as string;
if (!hogBefore || hogBefore === hogAfter) {
  fail("double-clicking the hedgehog did not change it");
}
pass("hedgehog easter egg cycles");

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

// Follow-up through the same input.
await page.fill(".qa-pill input", REPLAY_FOLLOW_UP);
await page.press(".qa-pill input", "Enter");
await page.waitForFunction(
  `document.querySelector(".qa-answer")?.textContent?.includes(${JSON.stringify(REPLAY_FOLLOW_UP_ANSWER)})`,
  undefined,
  { timeout: 15_000 },
);
pass("follow-up answer rendered");

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

if (pageErrors.length > 0) {
  fail(`page errors: ${pageErrors.join(" | ")}`);
}
pass("no page errors");

await browser.close();
renderer.close();
await replay.close();
console.log("quick-ask e2e: all checks passed");
