import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));
vi.mock("../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: false,
    isError: false,
    data: {
      title: "Session by ann@example.com",
      detail: "12 min · Jan 3",
      facts: ["42 clicks"],
    },
  }),
}));

import { openExternalUrl } from "../../../shell/openExternal";
import { ANONYMOUS_AUTH_STATE, useAuthStore } from "../../auth/store";
import { ReplayBlockCard } from "./ReplayBlockCard";

afterEach(() => {
  useAuthStore.setState({ authState: ANONYMOUS_AUTH_STATE });
});

describe("ReplayBlockCard", () => {
  it("shows the recording and links into PostHog's player, never an embed", () => {
    useAuthStore.setState({
      authState: {
        ...ANONYMOUS_AUTH_STATE,
        cloudRegion: "us",
        currentProjectId: 2,
      },
    });
    render(
      <Theme>
        <ReplayBlockCard spec={{ mode: "replay", sessionId: "s_01HQ4K" }} />
      </Theme>,
    );
    expect(screen.getByText("Session by ann@example.com")).toBeDefined();
    expect(screen.getByText("42 clicks")).toBeDefined();
    // Playback stays in PostHog: no iframe, no sharing prompt.
    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.queryByText(/link sharing/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Watch in PostHog/ }));
    expect(openExternalUrl).toHaveBeenCalledWith(
      "https://us.posthog.com/project/2/replay/s_01HQ4K",
    );
  });

  it("disables the watch button without a project to link into", () => {
    render(
      <Theme>
        <ReplayBlockCard spec={{ mode: "replay", sessionId: "s_01HQ4K" }} />
      </Theme>,
    );
    expect(
      screen.getByRole("button", { name: /Watch in PostHog/ }),
    ).toHaveProperty("disabled", true);
  });
});
