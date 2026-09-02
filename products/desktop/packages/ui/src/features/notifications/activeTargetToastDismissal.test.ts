import "reflect-metadata";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { describe, expect, it, vi } from "vitest";

const toastMock = vi.hoisted(() => ({ dismiss: vi.fn() }));
vi.mock("@posthog/ui/primitives/toast", () => ({ toast: toastMock }));

const routerMock = vi.hoisted(() => ({ handler: null as null | (() => void) }));
vi.mock("../../router/navigationBridge", () => ({
  subscribeToRouterResolved: (handler: () => void) => {
    routerMock.handler = handler;
    return () => {};
  },
}));

import { ActiveTargetToastDismissal } from "./activeTargetToastDismissal.contribution";
import type { IActiveView } from "./identifiers";

function start(activeTarget: NotificationTarget | undefined) {
  toastMock.dismiss.mockClear();
  routerMock.handler = null;
  const view: IActiveView = {
    hasFocus: () => true,
    getActiveTarget: () => activeTarget,
  };
  new ActiveTargetToastDismissal(view).start();
  return { resolveRoute: () => routerMock.handler?.() };
}

describe("ActiveTargetToastDismissal", () => {
  it("dismisses the opened target's toast on navigation", () => {
    const { resolveRoute } = start({ kind: "task", taskId: "task-1" });
    resolveRoute();
    expect(toastMock.dismiss).toHaveBeenCalledWith("task:task-1");
  });

  it("does nothing when the route is not a notifiable target", () => {
    const { resolveRoute } = start(undefined);
    resolveRoute();
    expect(toastMock.dismiss).not.toHaveBeenCalled();
  });
});
