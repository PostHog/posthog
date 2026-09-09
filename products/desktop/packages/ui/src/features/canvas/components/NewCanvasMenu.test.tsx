import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { NewCanvasMenu } from "./NewCanvasMenu";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  createSketchpad: vi.fn(),
  track: vi.fn(),
  error: vi.fn(),
  navigate: vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useCanvasTemplates", () => ({
  useCanvasTemplates: () => [],
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "personal-space", channelType: "personal" }],
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useCreateAndOpenDashboard: () => mocks.create,
}));
vi.mock("@posthog/ui/features/feature-flags/useSketchpadsFlag", () => ({
  useSketchpadsFlag: () => true,
}));
vi.mock("@posthog/ui/features/sketchpad/hooks/useSketchpadMutations", () => ({
  useSketchpadMutations: () => ({
    createSketchpad: mocks.createSketchpad,
    isCreating: false,
  }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: mocks.track }));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: mocks.error },
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToSpaceSketchpad: mocks.navigate,
}));

it.each(["canvas", "sketchpad"] as const)(
  "creates a %s in the fallback space and tracks the actual menu surface",
  async (kind) => {
    vi.clearAllMocks();
    mocks.create.mockResolvedValue(undefined);
    mocks.createSketchpad.mockRejectedValue(new Error("Connection lost"));
    const { unmount } = render(
      <NewCanvasMenu channelId={undefined} surface="sidebar" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "New canvas" }));
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: kind === "canvas" ? "New canvas" : /Sketchpad/i,
      }),
    );
    expect(mocks.track).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        action_type: "create",
        channel_id: "personal-space",
        surface: "sidebar",
        template_id: kind === "sketchpad" ? "sketchpad" : undefined,
      }),
    );
    if (kind === "canvas")
      expect(mocks.create).toHaveBeenCalledWith({
        channelId: "personal-space",
      });
    else {
      expect(mocks.createSketchpad).toHaveBeenCalledWith(
        "personal-space",
        expect.any(String),
      );
      await waitFor(() =>
        expect(mocks.error).toHaveBeenCalledWith("Couldn't create sketchpad", {
          description: "Connection lost",
        }),
      );
      expect(mocks.navigate).not.toHaveBeenCalled();
    }
    unmount();
  },
);
