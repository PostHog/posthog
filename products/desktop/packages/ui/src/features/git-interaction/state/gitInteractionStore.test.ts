import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));

import {
  type CreatePrDraftValues,
  useGitInteractionStore,
} from "./gitInteractionStore";

const KEY_A = "task-a:/repo/a";
const KEY_B = "task-b:/repo/b";

const EMPTY_DRAFT: CreatePrDraftValues = {
  branchName: "",
  commitMessage: "",
  prTitle: "",
  prBody: "",
};

function draft(values: Partial<CreatePrDraftValues>): CreatePrDraftValues {
  return { ...EMPTY_DRAFT, ...values };
}

function seed(drafts: Record<string, CreatePrDraftValues>) {
  useGitInteractionStore.setState({ createPrDrafts: drafts });
}

function setFields(values: Partial<CreatePrDraftValues>) {
  useGitInteractionStore.setState(draft(values));
}

function openCreatePr(draftKey: string, suggestedBranchName?: string) {
  useGitInteractionStore.getState().actions.openCreatePr({
    needsBranch: true,
    needsCommit: true,
    baseBranch: "main",
    suggestedBranchName,
    draftKey,
  });
}

function getFields(): CreatePrDraftValues {
  const s = useGitInteractionStore.getState();
  return {
    branchName: s.branchName,
    commitMessage: s.commitMessage,
    prTitle: s.prTitle,
    prBody: s.prBody,
  };
}

describe("gitInteractionStore Create PR drafts", () => {
  beforeEach(() => {
    useGitInteractionStore.setState({
      createPrOpen: false,
      createPrDrafts: {},
      activeCreatePrDraftKey: null,
      ...EMPTY_DRAFT,
    });
  });

  describe("openCreatePr hydration", () => {
    const cases: Array<{
      name: string;
      seeded: CreatePrDraftValues | null;
      suggested: string | undefined;
      expected: CreatePrDraftValues;
    }> = [
      {
        name: "uses defaults when no draft exists",
        seeded: null,
        suggested: "suggested-branch",
        expected: draft({ branchName: "suggested-branch" }),
      },
      {
        name: "hydrates fully from an existing draft",
        seeded: {
          branchName: "custom-branch",
          commitMessage: "my commit",
          prTitle: "My PR",
          prBody: "Body text",
        },
        suggested: "suggested-branch",
        expected: {
          branchName: "custom-branch",
          commitMessage: "my commit",
          prTitle: "My PR",
          prBody: "Body text",
        },
      },
      {
        name: "falls back to suggested branch when draft branchName is empty",
        seeded: draft({ commitMessage: "msg" }),
        suggested: "suggested-branch",
        expected: draft({
          branchName: "suggested-branch",
          commitMessage: "msg",
        }),
      },
      {
        name: "uses empty branch when no draft and no suggestion",
        seeded: null,
        suggested: undefined,
        expected: EMPTY_DRAFT,
      },
    ];

    for (const c of cases) {
      it(c.name, () => {
        if (c.seeded) seed({ [KEY_A]: c.seeded });
        openCreatePr(KEY_A, c.suggested);
        expect(getFields()).toEqual(c.expected);
        expect(useGitInteractionStore.getState().activeCreatePrDraftKey).toBe(
          KEY_A,
        );
      });
    }

    it("keeps each task's draft isolated when keys differ", () => {
      const otherDraft = draft({
        branchName: "branch-a",
        commitMessage: "commit a",
        prTitle: "title a",
        prBody: "body a",
      });
      seed({ [KEY_A]: otherDraft });

      openCreatePr(KEY_B, "suggested-b");

      expect(getFields()).toEqual(draft({ branchName: "suggested-b" }));
      expect(useGitInteractionStore.getState().createPrDrafts[KEY_A]).toEqual(
        otherDraft,
      );
    });
  });

  describe("closeCreatePr snapshot", () => {
    const cases: Array<{
      name: string;
      initialDraft: CreatePrDraftValues | null;
      typed: CreatePrDraftValues;
      expectedDraft: CreatePrDraftValues | undefined;
    }> = [
      {
        name: "saves non-empty fields under the active key",
        initialDraft: null,
        typed: {
          branchName: "typed-branch",
          commitMessage: "typed commit",
          prTitle: "typed title",
          prBody: "typed body",
        },
        expectedDraft: {
          branchName: "typed-branch",
          commitMessage: "typed commit",
          prTitle: "typed title",
          prBody: "typed body",
        },
      },
      {
        name: "does not write a draft when all fields are empty",
        initialDraft: null,
        typed: EMPTY_DRAFT,
        expectedDraft: undefined,
      },
      {
        name: "removes a previously saved draft when fields are now all empty",
        initialDraft: draft({
          branchName: "old",
          commitMessage: "old",
          prTitle: "old",
          prBody: "old",
        }),
        typed: EMPTY_DRAFT,
        expectedDraft: undefined,
      },
      {
        name: "saves even if only one field is populated",
        initialDraft: null,
        typed: draft({ prTitle: "only title" }),
        expectedDraft: draft({ prTitle: "only title" }),
      },
    ];

    for (const c of cases) {
      it(c.name, () => {
        if (c.initialDraft) seed({ [KEY_A]: c.initialDraft });
        openCreatePr(KEY_A);
        setFields(c.typed);

        useGitInteractionStore.getState().actions.closeCreatePr();

        const state = useGitInteractionStore.getState();
        expect(state.createPrOpen).toBe(false);
        expect(state.activeCreatePrDraftKey).toBeNull();
        expect(state.createPrDrafts[KEY_A]).toEqual(c.expectedDraft);
      });
    }
  });

  describe("clearCreatePrDraft", () => {
    it("removes the given key without touching others", () => {
      seed({
        [KEY_A]: draft({ commitMessage: "a" }),
        [KEY_B]: draft({ commitMessage: "b" }),
      });

      useGitInteractionStore.getState().actions.clearCreatePrDraft(KEY_A);

      const drafts = useGitInteractionStore.getState().createPrDrafts;
      expect(drafts[KEY_A]).toBeUndefined();
      expect(drafts[KEY_B]).toEqual(draft({ commitMessage: "b" }));
    });

    it("clears the active key so a subsequent closeCreatePr does not re-save", () => {
      openCreatePr(KEY_A, "suggested");
      setFields({ commitMessage: "typed commit", prTitle: "typed title" });

      const { clearCreatePrDraft, closeCreatePr } =
        useGitInteractionStore.getState().actions;
      clearCreatePrDraft(KEY_A);
      closeCreatePr();

      const state = useGitInteractionStore.getState();
      expect(state.createPrDrafts[KEY_A]).toBeUndefined();
      expect(state.activeCreatePrDraftKey).toBeNull();
      expect(state.createPrOpen).toBe(false);
    });

    it("leaves the active key alone when clearing a different key", () => {
      openCreatePr(KEY_A);

      useGitInteractionStore.getState().actions.clearCreatePrDraft(KEY_B);

      expect(useGitInteractionStore.getState().activeCreatePrDraftKey).toBe(
        KEY_A,
      );
    });
  });
});
