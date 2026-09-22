import { expect, test } from "../fixtures/electron";

test.describe("Smoke Tests", () => {
  test("app launches successfully and window appears", async ({
    electronApp,
    window,
  }) => {
    expect(electronApp).toBeTruthy();
    expect(window).toBeTruthy();

    const title = await window.title();
    expect(title).toContain("PostHog");
  });

  test("app renders initial UI (auth or main layout)", async ({ window }) => {
    await window.waitForSelector("#root > *", { timeout: 30000 });

    await window
      .locator('[data-testid="app-loading-shell"]')
      .waitFor({ state: "hidden", timeout: 30000 })
      .catch(() => {});

    const hasOnboarding = await window
      .locator("text=Welcome to")
      .first()
      .isVisible()
      .catch(() => false);

    const hasAuthScreen = await window
      .locator("text=Sign in")
      .first()
      .isVisible()
      .catch(() => false);

    const hasMainLayout = await window
      .locator("text=New task")
      .first()
      .isVisible()
      .catch(() => false);

    const hasSettings = await window
      .locator("text=Settings")
      .first()
      .isVisible()
      .catch(() => false);

    const isValidBootState =
      hasOnboarding || hasAuthScreen || hasMainLayout || hasSettings;
    expect(isValidBootState).toBe(true);
  });

  test("window has correct minimum dimensions", async ({
    electronApp,
    window,
  }) => {
    const browserWindow = await electronApp.browserWindow(window);
    const { bounds, minimumSize } = await browserWindow.evaluate(
      (nativeWindow) => ({
        bounds: nativeWindow.getBounds(),
        minimumSize: nativeWindow.getMinimumSize(),
      }),
    );

    expect(minimumSize).toEqual([800, 600]);
    expect(bounds.width).toBeGreaterThanOrEqual(minimumSize[0]);
    expect(bounds.height).toBeGreaterThanOrEqual(minimumSize[1]);
  });

  test("app does not crash within 10 seconds of boot", async ({
    electronApp,
    window,
  }) => {
    await window.waitForTimeout(10000);

    const isWindowClosed = window.isClosed();
    expect(isWindowClosed).toBe(false);

    const windows = electronApp.windows();
    expect(windows.length).toBeGreaterThan(0);
  });
});
