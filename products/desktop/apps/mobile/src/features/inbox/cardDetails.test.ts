import type {
  AnySignalReportArtefact,
  Signal,
  SuggestedReviewer,
} from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { cardReviewerNames, summarizeCardEvidence } from "./cardDetails";

function signal(source_product: string, source_type: string): Signal {
  return {
    signal_id: `${source_product}-${source_type}`,
    content: "",
    source_product,
    source_type,
    source_id: "s1",
    weight: 1,
    timestamp: "2026-01-01T00:00:00Z",
    extra: {},
  };
}

function artefact(type: string, content: unknown): AnySignalReportArtefact {
  return {
    id: `${type}-${Math.random()}`,
    created_at: "2026-01-01T00:00:00Z",
    type,
    content,
  } as AnySignalReportArtefact;
}

function finding(signalId: string): AnySignalReportArtefact {
  return artefact("signal_finding", {
    signal_id: signalId,
    relevant_code_paths: [],
    relevant_commit_hashes: {},
    data_queried: "",
    verified: true,
  });
}

function reviewers(...entries: SuggestedReviewer[]): AnySignalReportArtefact {
  return artefact("suggested_reviewers", entries);
}

function reviewer(
  github_login: string,
  overrides: Partial<SuggestedReviewer> = {},
): SuggestedReviewer {
  return {
    github_login,
    github_name: null,
    relevant_commits: [],
    user: null,
    ...overrides,
  };
}

describe("summarizeCardEvidence", () => {
  it("counts findings and session-replay problems separately", () => {
    const result = summarizeCardEvidence(
      [
        signal("session_replay", "session_problem"),
        signal("session_replay", "session_problem"),
        signal("error_tracking", "issue_created"),
      ],
      [finding("a"), finding("b"), finding("c"), artefact("note", {})],
    );
    expect(result).toEqual({ findingCount: 3, replayCount: 2 });
  });

  it("ignores non-session-problem replay signals", () => {
    // Only `session_problem` is the watchable evidence the detail page splits
    // out; other replay-sourced signals stay ordinary signals.
    const result = summarizeCardEvidence(
      [signal("session_replay", "rage_click")],
      [finding("a")],
    );
    expect(result).toEqual({ findingCount: 1, replayCount: 0 });
  });

  it.each<
    [string, Signal[] | undefined, AnySignalReportArtefact[] | undefined]
  >([
    ["nothing loaded yet", undefined, undefined],
    ["loaded but empty", [], []],
    ["only unrelated artefacts", [], [artefact("note", {})]],
    ["only ordinary signals", [signal("error_tracking", "issue_created")], []],
  ])(
    "returns null when there is no evidence: %s",
    (_name, signals, artefacts) => {
      expect(summarizeCardEvidence(signals, artefacts)).toBeNull();
    },
  );
});

describe("cardReviewerNames", () => {
  it("prefers the account name over the github handle", () => {
    const names = cardReviewerNames([
      reviewers(
        reviewer("octocat", {
          user: {
            id: 1,
            uuid: "u1",
            email: "ada@posthog.com",
            first_name: "Ada",
            last_name: "Lovelace",
          },
        }),
        reviewer("hedgehog", { github_name: "Hedge Hog" }),
        reviewer("bare"),
      ),
    ]);
    expect(names).toEqual(["Ada Lovelace", "Hedge Hog", "bare"]);
  });

  it.each<[string, AnySignalReportArtefact[] | undefined]>([
    ["artefacts were never fetched", undefined],
    ["there is no reviewer artefact", [artefact("note", {})]],
    ["the artefact is empty", [reviewers()]],
  ])("returns nothing when %s", (_name, artefacts) => {
    expect(cardReviewerNames(artefacts)).toEqual([]);
  });
});
