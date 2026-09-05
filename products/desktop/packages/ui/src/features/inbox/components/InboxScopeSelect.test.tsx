import { INBOX_SCOPE_FOR_YOU } from "@posthog/core/inbox/reportMembership";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({
    data: {
      uuid: "current-user",
      email: "ada@example.com",
      first_name: "Ada",
      last_name: "Lovelace",
    },
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxAvailableSuggestedReviewers: () => ({
    data: {
      count: 1,
      results: [
        {
          uuid: "teammate-1",
          name: "Grace Hopper",
          email: "grace@example.com",
          github_login: "grace",
        },
      ],
    },
  }),
}));

import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";

import { InboxScopeSelect } from "./InboxScopeSelect";

describe("InboxScopeSelect", () => {
  beforeEach(() => {
    useInboxReviewerScopeStore.setState({ scope: INBOX_SCOPE_FOR_YOU });
  });

  async function openPicker() {
    render(<InboxScopeSelect />);
    await userEvent.click(
      screen.getByRole("combobox", { name: /Self-driving scope/ }),
    );
  }

  it("offers the signed-in user a named row beside For you", async () => {
    await openPicker();

    expect(await screen.findByText("Ada Lovelace (you)")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /For you/ })).toBeInTheDocument();
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();
  });

  it("pins the inbox to the signed-in user when their row is picked", async () => {
    await openPicker();

    await userEvent.click(await screen.findByText("Ada Lovelace (you)"));

    expect(useInboxReviewerScopeStore.getState().scope).toBe(
      "teammate:current-user",
    );
  });

  it("keeps For you as a scope that resolves to whoever reads it", async () => {
    useInboxReviewerScopeStore.setState({ scope: "teammate:current-user" });
    await openPicker();

    await userEvent.click(await screen.findByText("For you"));

    expect(useInboxReviewerScopeStore.getState().scope).toBe(
      INBOX_SCOPE_FOR_YOU,
    );
  });
});
