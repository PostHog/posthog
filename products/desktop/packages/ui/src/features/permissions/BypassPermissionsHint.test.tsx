import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { TIP_KEYS } from "@posthog/ui/features/settings/tipKeys";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  localWorkspaces: true,
}));

vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: mocks.localWorkspaces }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/router/reportNavigation", () => ({
  settingsSourceHref: () => undefined,
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: React.ReactNode }) => (
    <a href="/">{children}</a>
  ),
}));

import { BypassPermissionsHint } from "./BypassPermissionsHint";
import type { PermissionToolCall } from "./types";

const approval = {
  toolCallId: "call-1",
  kind: "execute",
} as unknown as PermissionToolCall;

function findHint() {
  return screen.queryByText(/Allow bypass permissions/);
}

describe("BypassPermissionsHint", () => {
  beforeEach(() => {
    mocks.localWorkspaces = true;
    useSettingsStore.setState({
      allowBypassPermissions: false,
      tipsEnabled: true,
      hints: {},
      _hasHydrated: true,
    });
  });

  it("offers the setting on an approval prompt", () => {
    render(<BypassPermissionsHint toolCall={approval} />);

    expect(findHint()).toBeInTheDocument();
    expect(
      useSettingsStore.getState().hints[TIP_KEYS.bypassPermissionsMode]?.count,
    ).toBe(1);
  });

  it("stays shown after spending its own showing", () => {
    useSettingsStore.setState({
      hints: {
        [TIP_KEYS.bypassPermissionsMode]: { count: 11, learned: false },
      },
    });

    render(<BypassPermissionsHint toolCall={approval} />);

    expect(findHint()).toBeInTheDocument();
  });

  it.each([
    [
      "the person is asked a question",
      () => ({
        toolCall: {
          toolCallId: "call-2",
          kind: "question",
        } as unknown as PermissionToolCall,
      }),
    ],
    [
      "bypass is already allowed",
      () => {
        useSettingsStore.setState({ allowBypassPermissions: true });
        return { toolCall: approval };
      },
    ],
    [
      "the host has no harness settings",
      () => {
        mocks.localWorkspaces = false;
        return { toolCall: approval };
      },
    ],
    [
      "the lesson ran out of showings",
      () => {
        useSettingsStore.setState({
          hints: {
            [TIP_KEYS.bypassPermissionsMode]: { count: 12, learned: false },
          },
        });
        return { toolCall: approval };
      },
    ],
    [
      "tips are off",
      () => {
        useSettingsStore.setState({ tipsEnabled: false });
        return { toolCall: approval };
      },
    ],
  ])("says nothing when %s", (_case, setup) => {
    const props = setup();

    render(<BypassPermissionsHint {...props} />);

    expect(findHint()).not.toBeInTheDocument();
  });
});
