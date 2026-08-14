import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const getRecordingEmbedInfo = vi.fn();
vi.mock("../../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ getRecordingEmbedInfo }),
}));

// Keyed fake: metadata resolves to a preview, sharing to the mockable state.
let sharingState: { enabled: boolean; embedUrl: string | null } = {
  enabled: false,
  embedUrl: null,
};
vi.mock("../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: (key: unknown[]) => {
    if (key[0] === "replay-embed") {
      return { isPending: false, isError: false, data: sharingState };
    }
    return {
      isPending: false,
      isError: false,
      data: {
        title: "Session by ann@example.com",
        detail: "12 min · Jan 3",
        facts: ["42 clicks"],
      },
    };
  },
}));

import { ReplayBlockCard } from "./ReplayBlockCard";

function renderCard() {
  return render(
    <Theme>
      <ReplayBlockCard spec={{ mode: "replay", sessionId: "s_01HQ4K" }} />
    </Theme>,
  );
}

describe("ReplayBlockCard", () => {
  it("asks for consent before enabling sharing, then embeds the player", async () => {
    sharingState = { enabled: false, embedUrl: null };
    getRecordingEmbedInfo.mockResolvedValue({
      enabled: true,
      embedUrl: "https://us.posthog.com/embedded/tok123",
    });
    renderCard();
    expect(screen.getByText("Session by ann@example.com")).toBeDefined();
    expect(screen.queryByTestId("replay-player")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Watch here/ }));
    // No write yet: the consent text must come first.
    expect(getRecordingEmbedInfo).not.toHaveBeenCalled();
    expect(screen.getByText(/turns on link sharing/)).toBeDefined();

    fireEvent.click(
      screen.getByRole("button", { name: "Enable sharing and watch" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("replay-player")).toBeDefined(),
    );
    expect(getRecordingEmbedInfo).toHaveBeenCalledWith("s_01HQ4K", {
      enable: true,
    });
  });

  it("skips the consent step when sharing is already enabled", () => {
    sharingState = {
      enabled: true,
      embedUrl: "https://us.posthog.com/embedded/tok123",
    };
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Watch here/ }));
    expect(screen.getByTestId("replay-player")).toBeDefined();
    expect(screen.queryByText(/turns on link sharing/)).toBeNull();
  });
});
