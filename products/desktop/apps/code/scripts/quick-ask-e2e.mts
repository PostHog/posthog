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
// A string, not a function: tsx's esbuild transform injects helpers that do
// not exist inside the page.
await page.addInitScript(`
  window.electronTRPC = { sendMessage: () => {}, onMessage: () => {} };
  const listeners = [];
  window.__qaEmit = (event) => { for (const listener of listeners) listener(event); };
  window.quickAsk = {
    hide: () => {},
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

await page.goto(`${renderer.origin}/quick-ask.html`);
await page.waitForSelector(".qa-pill input", { timeout: 15_000 });
pass("panel booted");

await service.warm();
pass("sandbox warmed");

// First question through the real input.
await page.fill(".qa-pill input", REPLAY_QUESTION);
await page.press(".qa-pill input", "Enter");
await page.waitForSelector(".qa-actions", { timeout: 15_000 });

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
pass("answer rendered, stray turn skipped, no raw tags");

const chartTitle = (await page.evaluate(
  'document.querySelector("figure[data-testid=report-chart] span")?.textContent ?? ""',
)) as string;
if (chartTitle !== "Signups per day, last 7 days") {
  fail(`chart card missing or mistitled: ${JSON.stringify(chartTitle)}`);
}
pass("hogql block tag rendered as a chart card");

// Follow-up through the same input.
await page.fill(".qa-pill input", REPLAY_FOLLOW_UP);
await page.press(".qa-pill input", "Enter");
await page.waitForFunction(
  `document.querySelector(".qa-answer")?.textContent?.includes(${JSON.stringify(REPLAY_FOLLOW_UP_ANSWER)})`,
  undefined,
  { timeout: 15_000 },
);
pass("follow-up answer rendered");

if (pageErrors.length > 0) {
  fail(`page errors: ${pageErrors.join(" | ")}`);
}
pass("no page errors");

await browser.close();
renderer.close();
await replay.close();
console.log("quick-ask e2e: all checks passed");
