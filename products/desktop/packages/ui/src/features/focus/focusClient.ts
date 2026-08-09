import type { FocusControllerDeps } from "@posthog/core/focus/service";

export type { FocusControllerDeps };

export const FOCUS_CONTROLLER_DEPS = Symbol.for(
  "posthog.ui.FocusControllerDeps",
);
