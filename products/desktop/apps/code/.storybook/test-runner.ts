import path from "node:path";
import { fileURLToPath } from "node:url";
import type { TestRunnerConfig } from "@storybook/test-runner";
import { getStoryContext, waitForPageReady } from "@storybook/test-runner";
import { toMatchImageSnapshot } from "jest-image-snapshot";
import type { Page } from "playwright";
import type { Parameters } from "storybook/internal/types";

// Ported from posthog/posthog's common/storybook/.storybook/test-runner.ts,
// trimmed to what this app needs (no MSW, kea, iframes, or webkit).

declare module "storybook/internal/types" {
  interface Parameters {
    layout?: "padded" | "fullscreen" | "centered";
    testOptions?: {
      /** Wait for spinners/skeletons to disappear before snapshotting. Defaults to true. */
      waitForLoadersToDisappear?: boolean;
      /** Extra selector(s) that must be present before snapshotting. */
      waitForSelector?: string | string[];
      /** Screenshot this element instead of #storybook-root. Non-fullscreen stories only. */
      snapshotTargetSelector?: string;
      /** Viewport size for this story. Defaults to 1280x720. */
      viewport?: { width: number; height: number };
      /** Themes to snapshot. Defaults to both. */
      themes?: SnapshotTheme[];
    };
  }
}

type SnapshotTheme = "dark" | "light";
const THEMES: SnapshotTheme[] = ["dark", "light"];

const SNAPSHOTS_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "__snapshots__",
);
const DEFAULT_VIEWPORT = { width: 1280, height: 720 };
const JEST_TIMEOUT_MS = 60000;

const LOADER_SELECTORS = [
  ".quill-spinner",
  ".quill-skeleton",
  ".quill-button__spinner",
  '[aria-busy="true"]',
];

// Radix Themes portals dialogs/popovers/tooltips outside #storybook-root, so a
// plain root screenshot would miss them - the snapshot clip is expanded to
// cover any of these that are visible.
const OVERLAY_SELECTORS = [
  "[data-radix-popper-content-wrapper]",
  '[role="dialog"]',
  '[role="alertdialog"]',
  '[role="tooltip"]',
];

const config: TestRunnerConfig = {
  setup() {
    expect.extend({ toMatchImageSnapshot });
    jest.retryTimes(2, { logErrorsBeforeRetry: true });
    jest.setTimeout(JEST_TIMEOUT_MS);
  },
  async preVisit(page, context) {
    const storyContext = await getStoryContext(page, context);
    const viewport =
      storyContext.parameters?.testOptions?.viewport ?? DEFAULT_VIEWPORT;
    await page.setViewportSize(viewport);
  },
  async postVisit(page, context) {
    const storyContext = await getStoryContext(page, context);
    const { parameters } = storyContext;
    const testOptions = parameters?.testOptions ?? {};

    await waitForPageReady(page);
    await page.evaluate(() => document.fonts.ready);
    await disableAnimations(page);

    if (testOptions.waitForLoadersToDisappear ?? true) {
      await page.waitForSelector(LOADER_SELECTORS.join(","), {
        state: "hidden",
        timeout: 5000,
      });
    }
    for (const selector of toArray(testOptions.waitForSelector)) {
      await page.waitForSelector(selector);
    }

    for (const theme of testOptions.themes ?? THEMES) {
      await takeSnapshotWithTheme(page, context.id, theme, parameters);
    }
  },
  tags: {
    skip: ["test-skip"],
  },
};

function toArray(value: string | string[] | undefined): string[] {
  return value === undefined ? [] : Array.isArray(value) ? value : [value];
}

async function disableAnimations(page: Page): Promise<void> {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        transition-duration: 0s !important;
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        caret-color: transparent !important;
      }
    `,
  });
}

async function takeSnapshotWithTheme(
  page: Page,
  storyId: string,
  theme: SnapshotTheme,
  parameters: Parameters,
): Promise<void> {
  // The preview's Theme decorator reads context.globals.theme, so flipping the
  // global re-renders the story in the other theme without a page reload.
  await page.evaluate((newTheme) => {
    (window as any).__STORYBOOK_ADDONS_CHANNEL__.emit("updateGlobals", {
      globals: { theme: newTheme, backgrounds: { value: newTheme } },
    });
  }, theme);
  await waitForPageReady(page);
  await waitForImagesToLoad(page);
  await resetScroll(page);
  await waitForDomStability(page);
  // waitForDomStability only polls scrollWidth/Height, so a theme flip's
  // color-only repaint (no layout change) isn't visible to it. Wait for a
  // paint, plus a short settle: the theme global lands via a channel event
  // and React's commit isn't guaranteed within the next frame under CI load.
  await waitForNextPaint(page);
  await page.waitForTimeout(250);

  const image = await captureScreenshot(page, parameters);
  expect(image).toMatchImageSnapshot({
    customSnapshotsDir: SNAPSHOTS_DIR,
    customSnapshotIdentifier: `${storyId}--${theme}`,
    comparisonMethod: "ssim",
    failureThreshold: 0.01,
    failureThresholdType: "percent",
  });
}

async function captureScreenshot(
  page: Page,
  parameters: Parameters,
): Promise<Buffer> {
  if (parameters?.layout === "fullscreen") {
    return page.screenshot();
  }
  const targetSelector = parameters?.testOptions?.snapshotTargetSelector;
  if (targetSelector) {
    return page.locator(targetSelector).screenshot();
  }
  const clip = await componentClip(page);
  return clip ? page.screenshot({ clip }) : page.screenshot();
}

/** Union bounding box of #storybook-root and any portaled overlays, clamped to the viewport. */
async function componentClip(
  page: Page,
): Promise<{ x: number; y: number; width: number; height: number } | null> {
  return page.evaluate((overlaySelectors) => {
    const elements = [
      document.getElementById("storybook-root"),
      ...document.querySelectorAll(overlaySelectors),
    ];
    const rects = elements
      .filter((el): el is HTMLElement => el instanceof HTMLElement)
      .map((el) => el.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0);
    if (rects.length === 0) {
      return null;
    }
    const left = Math.max(0, Math.min(...rects.map((r) => r.left)));
    const top = Math.max(0, Math.min(...rects.map((r) => r.top)));
    const right = Math.min(
      window.innerWidth,
      Math.max(...rects.map((r) => r.right)),
    );
    const bottom = Math.min(
      window.innerHeight,
      Math.max(...rects.map((r) => r.bottom)),
    );
    if (right <= left || bottom <= top) {
      return null;
    }
    return { x: left, y: top, width: right - left, height: bottom - top };
  }, OVERLAY_SELECTORS.join(","));
}

async function waitForImagesToLoad(page: Page): Promise<void> {
  await page
    .waitForFunction(
      () =>
        Array.from(document.querySelectorAll("img[src]")).every(
          (img) => (img as HTMLImageElement).naturalWidth > 0,
        ),
      undefined,
      { timeout: 5000 },
    )
    .catch(() => undefined);
}

/** Waits for two animation frames so a color-only repaint (no layout change) finishes painting. */
async function waitForNextPaint(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

async function resetScroll(page: Page): Promise<void> {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    for (const el of document.querySelectorAll(
      ".overflow-auto, .overflow-y-auto, .overflow-x-auto",
    )) {
      el.scrollTop = 0;
      el.scrollLeft = 0;
    }
  });
}

/** Wait until the body's scroll size is unchanged across consecutive checks, so late layout shifts don't race the screenshot. */
async function waitForDomStability(page: Page): Promise<void> {
  await page
    .waitForFunction(
      () => {
        const w = window as any;
        const size = `${document.body.scrollWidth}x${document.body.scrollHeight}`;
        if (w.__vrLastSize === size) {
          w.__vrStableCount = (w.__vrStableCount ?? 0) + 1;
        } else {
          w.__vrStableCount = 0;
          w.__vrLastSize = size;
        }
        return w.__vrStableCount >= 3;
      },
      undefined,
      { timeout: 3000, polling: 100 },
    )
    .catch(() => undefined);
}

export default config;
