import { APP_LIFECYCLE_SERVICE } from "@posthog/platform/app-lifecycle";
import { APP_META_SERVICE } from "@posthog/platform/app-meta";
import { BUNDLED_RESOURCES_SERVICE } from "@posthog/platform/bundled-resources";
import { CLIPBOARD_SERVICE } from "@posthog/platform/clipboard";
import { CONTEXT_MENU_SERVICE } from "@posthog/platform/context-menu";
import { DIALOG_SERVICE } from "@posthog/platform/dialog";
import { FILE_ICON_SERVICE } from "@posthog/platform/file-icon";
import { IMAGE_PROCESSOR_SERVICE } from "@posthog/platform/image-processor";
import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import { NOTIFIER_SERVICE } from "@posthog/platform/notifier";
import { POWER_MANAGER_SERVICE } from "@posthog/platform/power-manager";
import { SECURE_STORAGE_SERVICE } from "@posthog/platform/secure-storage";
import { STORAGE_PATHS_SERVICE } from "@posthog/platform/storage-paths";
import { UPDATER_SERVICE } from "@posthog/platform/updater";
import { URL_LAUNCHER_SERVICE } from "@posthog/platform/url-launcher";
import { Container, injectable } from "inversify";
import { describe, expect, it } from "vitest";

const PLATFORM_IDENTIFIERS = {
  APP_LIFECYCLE_SERVICE,
  APP_META_SERVICE,
  BUNDLED_RESOURCES_SERVICE,
  CLIPBOARD_SERVICE,
  CONTEXT_MENU_SERVICE,
  DIALOG_SERVICE,
  FILE_ICON_SERVICE,
  IMAGE_PROCESSOR_SERVICE,
  MAIN_WINDOW_SERVICE,
  NOTIFIER_SERVICE,
  POWER_MANAGER_SERVICE,
  SECURE_STORAGE_SERVICE,
  STORAGE_PATHS_SERVICE,
  UPDATER_SERVICE,
  URL_LAUNCHER_SERVICE,
};

describe("platform service identifiers", () => {
  it("defines a symbol for every platform capability", () => {
    const identifiers = Object.values(PLATFORM_IDENTIFIERS);
    expect(identifiers).toHaveLength(15);
    for (const identifier of identifiers) {
      expect(typeof identifier).toBe("symbol");
    }
  });

  it("keys every identifier under the posthog.platform namespace", () => {
    for (const identifier of Object.values(PLATFORM_IDENTIFIERS)) {
      expect(identifier.description).toMatch(/^posthog\.platform\./);
    }
  });

  it("uses mutually unique identifiers", () => {
    const identifiers = Object.values(PLATFORM_IDENTIFIERS);
    expect(new Set(identifiers).size).toBe(identifiers.length);
  });

  it("resolves a legacy alias to the same singleton as the platform token", () => {
    const LEGACY_TOKEN = Symbol.for("test.legacy.clipboard");

    @injectable()
    class FakeClipboard {
      writeText() {
        return Promise.resolve();
      }
    }

    const container = new Container({ defaultScope: "Singleton" });
    container.bind(CLIPBOARD_SERVICE).to(FakeClipboard);
    container.bind(LEGACY_TOKEN).toService(CLIPBOARD_SERVICE);

    const viaPlatform = container.get(CLIPBOARD_SERVICE);
    const viaLegacy = container.get(LEGACY_TOKEN);

    expect(viaPlatform).toBeInstanceOf(FakeClipboard);
    expect(viaLegacy).toBe(viaPlatform);
  });
});
