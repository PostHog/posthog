import type {
  SignalReport,
  SignalReportArtefactsResponse,
  SuggestedReviewer,
} from "@posthog/shared/domain-types";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  currentUserUuid: "user-me" as string | undefined,
  mutate: vi.fn(),
  track: vi.fn(),
}));

vi.mock("@/features/auth", () => ({
  useUserQuery: () => ({ data: { uuid: mocks.currentUserUuid } }),
}));

vi.mock("../hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: artefacts }),
  useUpdateSuggestedReviewers: () => ({
    mutate: mocks.mutate,
    isPending: false,
  }),
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { INBOX_REPORT_ACTION: "Inbox report action" },
  computeReportAgeHours: () => 0,
  useAnalytics: () => ({ track: mocks.track }),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#888" } }),
}));

// react-native-web's Image touches `window` in a mount effect, which the node
// test environment lacks. A stub keeps the avatar stack renderable.
vi.mock("react-native", async () => {
  const actual = await import("react-native-web");
  const { createElement } = await import("react");
  return {
    ...actual,
    Image: (props: Record<string, unknown>) => createElement("Image", props),
  };
});

import { SuggestedReviewerAvatarStack } from "./SuggestedReviewerAvatarStack";

function reviewer(login: string, uuid: string): SuggestedReviewer {
  return {
    github_login: login,
    github_name: login,
    relevant_commits: [],
    user: {
      id: 1,
      uuid,
      email: `${login}@example.com`,
      first_name: login,
      last_name: "",
    },
  };
}

const me = reviewer("alice", "user-me");
const teammate = reviewer("bob", "user-bob");
const report = { id: "report-1", title: "Checkout failures" } as SignalReport;
const artefacts: SignalReportArtefactsResponse = {
  count: 1,
  results: [
    {
      id: "reviewers-1",
      type: "suggested_reviewers",
      created_at: "2026-01-01T00:00:00Z",
      content: [me, teammate],
    },
  ],
};

function mount() {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(SuggestedReviewerAvatarStack, { report }));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function removeButton(renderer: ReturnType<typeof create>) {
  return renderer.root.findAll(
    (node) =>
      node.props.accessibilityLabel === "Remove yourself from reviewers",
  );
}

describe("SuggestedReviewerAvatarStack", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.currentUserUuid = "user-me";
  });

  it.each([
    ["the current user is a reviewer", "user-me", true],
    ["the current user is not a reviewer", "user-other", false],
  ])("is interactive when %s", (_case, currentUserUuid, interactive) => {
    mocks.currentUserUuid = currentUserUuid;
    expect(removeButton(mount()).length > 0).toBe(interactive);
  });

  it("removes the current user and tracks the list action", () => {
    const renderer = mount();
    act(() => {
      removeButton(renderer)[0].props.onPress();
    });

    expect(mocks.mutate).toHaveBeenCalledWith({
      artefactId: "reviewers-1",
      content: [{ github_login: "bob" }],
      optimisticReviewers: [teammate],
    });
    expect(mocks.track).toHaveBeenCalledWith(
      "Inbox report action",
      expect.objectContaining({
        action_type: "remove_suggested_reviewer",
        surface: "list_row",
        suggested_reviewer_login: "alice",
        suggested_reviewer_uuid: "user-me",
      }),
    );
  });
});
