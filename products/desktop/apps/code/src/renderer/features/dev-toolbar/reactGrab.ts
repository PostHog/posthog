import { logger } from "@utils/logger";
import type { ReactGrabAPI } from "react-grab/core";

declare global {
  interface Window {
    // react-scan hands Cmd+C over to react-grab when it sees this global, but
    // only react-grab's main entry publishes it, and that entry self-starts on
    // import. We load the core entry, so we publish it ourselves.
    __REACT_GRAB__?: ReactGrabAPI;
  }
}

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
    if (!api && !enabled) {
      return;
    }
    const mod = await loadReactGrab();
    if (!api) {
      api = mod.init({ enabled, telemetry: false });
    }
    // init seeds the live state from react-grab's own persisted toolbar state,
    // so a toolbar collapsed in an earlier session outranks `enabled` here.
    api.setEnabled(enabled);
    if (enabled) {
      window.__REACT_GRAB__ = api;
    } else if (window.__REACT_GRAB__ === api) {
      delete window.__REACT_GRAB__;
    }
  } catch (error) {
    log.warn("Failed to toggle react-grab", { error });
  }
}
