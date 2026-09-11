import { ApiRequestError } from "@posthog/api-client/fetcher";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextWikiProposalsPane } from "./ContextWikiProposalsPane";

const state = vi.hoisted(() => ({
  proposals: [
    {
      id: "proposal-1",
      path: "areas/example.md",
      original_content: "Old text",
      content: "New text <img src='https://example.com/image'>",
    },
  ],
  mutate: vi.fn(),
  refetch: vi.fn(),
  error: null as Error | null,
  queryError: null as Error | null,
  isPending: false,
  isLoading: false,
}));

vi.mock("../hooks/useContextWiki", () => ({
  useContextWikiProposals: () => ({
    data: state.proposals,
    error: state.queryError,
    isLoading: state.isLoading,
    refetch: state.refetch,
  }),
  useApplyContextWikiProposal: () => ({
    mutate: state.mutate,
    error: state.error,
    isPending: state.isPending,
    isSuccess: false,
  }),
}));
vi.mock("@pierre/diffs/react", () => ({
  MultiFileDiff: ({
    oldFile,
    newFile,
  }: {
    oldFile: { contents: string };
    newFile: { contents: string };
  }) => (
    <pre>
      {oldFile.contents}
      {"\n"}
      {newFile.contents}
    </pre>
  ),
}));

describe("ContextWikiProposalsPane", () => {
  beforeEach(() => {
    state.mutate.mockClear();
    state.error = null;
    state.queryError = null;
    state.isPending = false;
    state.isLoading = false;
  });

  it("requires selection and applies only the reviewed proposal ID", async () => {
    const user = userEvent.setup();
    render(<ContextWikiProposalsPane />);
    expect(
      screen.queryByRole("button", { name: "Apply to shared wiki" }),
    ).toBeNull();
    await user.click(screen.getByRole("button", { name: "areas/example.md" }));
    expect(screen.getByText(/Old text/)).toHaveTextContent("New text");
    expect(document.querySelector("img")).toBeNull();
    expect(state.mutate).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Apply to shared wiki" }),
    );
    expect(state.mutate).toHaveBeenCalledWith("proposal-1");
  });

  it.each(["pending", "conflict"])("blocks approval when %s", async (mode) => {
    state.isPending = mode === "pending";
    state.error =
      mode === "conflict" ? new ApiRequestError(409, "Stale") : null;
    render(<ContextWikiProposalsPane />);
    await userEvent.click(
      screen.getByRole("button", { name: "areas/example.md" }),
    );
    const button = screen.getByRole("button", {
      name: mode === "pending" ? "Applying…" : "Apply to shared wiki",
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(button);
    expect(state.mutate).not.toHaveBeenCalled();
    if (mode === "conflict")
      expect(screen.getByRole("alert")).toHaveTextContent("submit a new edit");
  });

  it("shows an actionable load error", () => {
    state.queryError = new Error("Unavailable");
    render(<ContextWikiProposalsPane />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
