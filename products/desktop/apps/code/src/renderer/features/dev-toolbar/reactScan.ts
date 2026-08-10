import { logger } from "@utils/logger";

const log = logger.scope("react-scan");

let initialized = false;
let loadPromise: Promise<typeof import("react-scan")> | null = null;

async function loadReactScan() {
  if (!loadPromise) {
    loadPromise = import("react-scan");
  }
  return loadPromise;
}

export async function setReactScanEnabled(enabled: boolean): Promise<void> {
  try {
    const mod = await loadReactScan();
    if (!initialized) {
      mod.scan({ enabled, showToolbar: enabled });
      initialized = true;
      return;
    }
    mod.setOptions({ enabled, showToolbar: enabled });
  } catch (error) {
    log.warn("Failed to toggle react-scan", { error });
  }
}
