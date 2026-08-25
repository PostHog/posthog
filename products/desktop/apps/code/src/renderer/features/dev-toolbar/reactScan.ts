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
  // react-scan must be imported before React runs. A packaged build never does
  // that, so loading it there only makes it log a console.error, which error
  // tracking then captures. Keep it dev-only at the source.
  if (!import.meta.env.DEV) {
    return;
  }
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
