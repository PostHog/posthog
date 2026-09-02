import { logger } from "@utils/logger";
import type { ReactGrabAPI } from "react-grab/core";

const log = logger.scope("react-grab");

let api: ReactGrabAPI | null = null;
let loadPromise: Promise<typeof import("react-grab/core")> | null = null;

async function loadReactGrab() {
  if (!loadPromise) {
    loadPromise = import("react-grab/core");
  }
  return loadPromise;
}

export async function setReactGrabEnabled(enabled: boolean): Promise<void> {
  try {
    const mod = await loadReactGrab();
    if (!api) {
      api = mod.init({ enabled, telemetry: false });
      return;
    }
    api.setEnabled(enabled);
  } catch (error) {
    log.warn("Failed to toggle react-grab", { error });
  }
}
