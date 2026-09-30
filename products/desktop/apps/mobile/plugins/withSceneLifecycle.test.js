import { describe, expect, it } from "vitest";
import withSceneLifecycle from "./withSceneLifecycle";

const appDelegate = `class AppDelegate: ExpoAppDelegate {
  var window: UIWindow?
  func application() {
    window = UIWindow(frame: UIScreen.main.bounds)
    factory.startReactNative(
      withModuleName: "main",
      in: window,
      launchOptions: launchOptions)
  }
}`;

async function apply(contents, language = "swift") {
  const config = withSceneLifecycle({ name: "PostHog", slug: "posthog" });
  const result = await config.mods.ios.appDelegate({
    ...config,
    modRequest: { platform: "ios", modName: "appDelegate" },
    modResults: { contents, language },
  });
  return result.modResults.contents;
}

describe("withSceneLifecycle", () => {
  it("moves window creation into a single scene delegate across repeated prebuilds", async () => {
    const result = await apply(appDelegate);
    expect(result).not.toContain("UIWindow(frame: UIScreen.main.bounds)");
    expect(result).toContain("UIWindow(windowScene: windowScene)");
    expect(result).toContain("initialLaunchOptions = launchOptions");
    expect(result).toContain(
      "var launchOptions = appDelegate.initialLaunchOptions ?? [:]",
    );
    expect(await apply(result)).toBe(result);
  });

  it.each([
    [appDelegate.replace("factory.startReactNative", "factory.start"), "swift"],
    [appDelegate.replace("  var window: UIWindow?", ""), "swift"],
    [appDelegate, "objc"],
  ])(
    "rejects unsupported native templates instead of generating a broken app",
    async (contents, language) => {
      await expect(apply(contents, language)).rejects.toThrow();
    },
  );
});
