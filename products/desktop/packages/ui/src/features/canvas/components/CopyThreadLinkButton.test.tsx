import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  copyChannelLink: vi.fn(),
  copyBranchName: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@posthog/ui/features/canvas/utils/copyChannelLink", () => ({
  copyChannelLink: mocks.copyChannelLink,
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

import { CopyThreadLinkButton } from "./CopyThreadLinkButton";

describe("CopyThreadLinkButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows and runs the ordered thread copy actions", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockImplementation(
      async (text: string) => {
        mocks.copyBranchName(text);
      },
    );
    render(
      <CopyThreadLinkButton
        branchName="posthog/example"
        channelId="channel-id"
        taskId="task-id"
      />,
    );

    const trigger = screen.getByRole("button", { name: "Thread actions" });
    await user.click(trigger);

    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Copy link to thread",
      "Copy branch name",
    ]);

    await user.click(items[0]);
    expect(mocks.copyChannelLink).toHaveBeenCalledWith(
      "channel-id",
      "title_bar",
      "task-id",
    );

    await user.click(trigger);
    await user.click(
      await screen.findByRole("menuitem", { name: "Copy branch name" }),
    );
    expect(mocks.copyBranchName).toHaveBeenCalledWith("posthog/example");
    await waitFor(() => {
      expect(mocks.toastSuccess).toHaveBeenCalledWith("Branch name copied");
    });
  });

  it("does not show the branch action without a branch name", async () => {
    const user = userEvent.setup();
    render(<CopyThreadLinkButton channelId="channel-id" taskId="task-id" />);

    await user.click(screen.getByRole("button", { name: "Thread actions" }));

    expect(
      await screen.findByRole("menuitem", { name: "Copy link to thread" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "Copy branch name" }),
    ).not.toBeInTheDocument();
  });
});
