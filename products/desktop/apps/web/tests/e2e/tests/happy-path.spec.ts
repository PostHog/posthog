import { expect, test } from "@playwright/test";

// Hermetic happy path for the cloud-only web host, up to the OAuth wall. Real
// login needs PostHog cloud + a popup IdP, so these stop at the sign-in card;
// they prove the bundle loads, the DI container wires (a missing host-capability
// binding would throw at boot), lazy routes resolve, and the app renders in a
// real browser — the "portability smoke test" the README describes.

test.describe("web host happy path", () => {
  test("boots to the onboarding welcome screen", async ({ page }) => {
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

    // A clean browser has no persisted onboarding state, so the first screen is
    // the welcome step.
    await expect(page.getByText("Welcome to")).toBeVisible({ timeout: 30_000 });
    await expect(
      page.getByRole("button", { name: "Start shipping" }),
    ).toBeVisible();

    // Nothing threw during boot (e.g. an unbound DI capability).
    expect(errors).toEqual([]);
  });

  test("advances from welcome to the PostHog sign-in card", async ({
    page,
  }) => {
    await page.goto("/");
    const startButton = page.getByRole("button", { name: "Start shipping" });
    await startButton.waitFor({ state: "visible", timeout: 30_000 });
    await startButton.click();

    // The project-select step shows the sign-in card while anonymous — the end
    // of the hermetic path (real OAuth needs a live IdP).
    await expect(
      page.getByText("Sign in / sign up with PostHog").first(),
    ).toBeVisible({ timeout: 30_000 });
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
