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

  test("window has correct minimum dimensions", async ({ window }) => {
    // The main process maximizes the window on ready-to-show, which can land
    // after domcontentloaded. Poll so the assertion sees the final size, not
    // the 600px outer frame the window opens with.
    const bounds = () =>
      window.evaluate(() => ({
        width: window.innerWidth,
        height: window.innerHeight,
      }));

    await expect
      .poll(async () => (await bounds()).width, { timeout: 10000 })
      .toBeGreaterThanOrEqual(900);
    await expect
      .poll(async () => (await bounds()).height, { timeout: 10000 })
      .toBeGreaterThanOrEqual(600);
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
