import { Jimp } from "jimp";
import { firstRenderTimeout } from "../arch";
import { expect, test } from "../fixtures/electron";

test.describe("Visual Stability", () => {
  test("consecutive screenshots are visually identical (no flickering)", async ({
    window,
  }) => {
    await window.waitForSelector("#root > *", { timeout: firstRenderTimeout });
    await window
      .locator('[data-testid="app-loading-shell"]')
      .waitFor({ state: "hidden", timeout: firstRenderTimeout })
      .catch(() => {});

    // Wait for the app to fully settle (animations, data loading, spinners)
    await window.waitForTimeout(5000);

    const screenshot1 = await window.screenshot();
    const screenshot1Hash = (await Jimp.read(screenshot1)).hash();

    const screenshot2 = await window.screenshot();
    const screenshot2Hash = (await Jimp.read(screenshot2)).hash();

    expect(screenshot1Hash).toEqual(screenshot2Hash);
  });
});
