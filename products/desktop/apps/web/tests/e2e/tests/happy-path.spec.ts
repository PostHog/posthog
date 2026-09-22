import { expect, test } from "@playwright/test";

// Hermetic happy path for the cloud-only web host, up to the OAuth wall. Real
// login needs PostHog cloud + a popup IdP, so these stop at the sign-in card;
// they prove the bundle loads, the DI container wires (a missing host-capability
// binding would throw at boot), lazy routes resolve, and the app renders in a
// real browser — the "portability smoke test" the README describes.

test.describe("web host happy path", () => {
  test("boots to the onboarding sign-in card", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    await page.goto("/");

    // #root populates once React mounts.
    await expect(page.locator("#root > *").first()).toBeVisible({
      timeout: 30_000,
    });

    // The animated boot logo clears once bootstrap (auth restore) completes.
    await page
      .getByTestId("app-loading-logo")
      .waitFor({ state: "hidden", timeout: 30_000 })
      .catch(() => {});

    await expect(
      page.getByRole("button", { name: "Sign in with PostHog" }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Back" })).toHaveCount(0);

    // Nothing threw during boot (e.g. an unbound DI capability).
    expect(errors).toEqual([]);
  });

  test("the OAuth /callback relay page renders without crashing", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    // Hitting /callback directly (no code/state) exercises the popup-landing
    // relay path in main.tsx without booting the full app.
    await page.goto("/callback");

    await expect(
      page.getByText("Signed in — you can close this window."),
    ).toBeVisible({ timeout: 15_000 });
    expect(errors).toEqual([]);
  });
});
