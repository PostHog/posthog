import { useIntegrationStore } from "@posthog/ui/features/integrations/store";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskRepositoryDialog } from "./TaskRepositoryDialog";

vi.mock(
  "@posthog/ui/features/settings/sections/ProjectGithubConnectionSection",
  () => ({
    ProjectGithubConnectionSection: () => (
      <button type="button">Connect GitHub</button>
    ),
  }),
);

vi.mock(
  "@posthog/ui/features/integrations/useIntegrations",
  async (importOriginal) => ({
    ...(await importOriginal()),
    useGithubRepositories: () => ({
      repositories: [],
      getIntegrationIdForRepo: vi.fn(),
      isPending: false,
      isFetchingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
    }),
  }),
);

describe("TaskRepositoryDialog", () => {
  beforeEach(() => {
    useIntegrationStore.getState().setIntegrations([]);
  });

  it("applies an empty repository selection", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    useIntegrationStore.getState().setIntegrations([{ id: 7, kind: "github" }]);

    render(
      <TaskRepositoryDialog
        open
        onOpenChange={vi.fn()}
        cloud
        repositories={["posthog/posthog"]}
        integrationId={7}
        folder=""
        onApply={onApply}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Remove posthog/posthog" }),
    );

    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).not.toHaveAttribute("aria-disabled", "true");
    await user.click(apply);

    expect(onApply).toHaveBeenCalledWith({
      repositories: [],
      integrationId: null,
      folder: "",
      saveToSpace: false,
    });
  });

  it("shows GitHub connection setup instead of repository controls when disconnected", () => {
    render(
      <TaskRepositoryDialog
        open
        onOpenChange={vi.fn()}
        cloud
        repositories={[]}
        integrationId={null}
        folder=""
        onApply={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Connect GitHub" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Apply" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Use these repositories for the whole space"),
    ).not.toBeInTheDocument();
  });
});
