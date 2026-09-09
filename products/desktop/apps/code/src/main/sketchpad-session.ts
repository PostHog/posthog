import { SKETCHPAD_PARTITION } from "@posthog/shared";
import { session } from "electron";
import { isolateGuestSession } from "./platform-adapters/sandboxed-webviews";
import { registerSketchpadModulesProtocol } from "./protocols/sketchpad-modules";
import { sketchpadModulesResourcesDir } from "./protocols/sketchpad-modules-dir";

export function prepareSketchpadSession(): void {
  const sketchpadSession = session.fromPartition(SKETCHPAD_PARTITION);
  isolateGuestSession(sketchpadSession);
  registerSketchpadModulesProtocol(
    sketchpadSession.protocol,
    sketchpadModulesResourcesDir(),
  );
}
