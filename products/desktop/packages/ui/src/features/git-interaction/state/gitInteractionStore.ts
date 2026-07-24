import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  CommitNextStep,
  CreatePrStep,
  GitMenuActionId,
  PushMode,
  PushState,
} from "../types";

export type { CommitNextStep, PushMode, PushState };

export interface CreatePrDraftValues {
  branchName: string;
  commitMessage: string;
  prTitle: string;
  prBody: string;
}

interface GitInteractionState {
  commitOpen: boolean;
  pushOpen: boolean;
  createPrOpen: boolean;
  branchOpen: boolean;
  commitMessage: string;
  commitNextStep: CommitNextStep;
  pushMode: PushMode;
  pushState: PushState;
  pushError: string | null;
  prTitle: string;
  prBody: string;
  createPrStep: CreatePrStep;
  createPrError: string | null;
  createPrNeedsBranch: boolean;
  createPrNeedsCommit: boolean;
  createPrBaseBranch: string | null;
  createPrDraft: boolean;
  createPrFailedStep: CreatePrStep | null;
  commitError: string | null;
  branchName: string;
  branchError: string | null;
  isSubmitting: boolean;
  isGeneratingCommitMessage: boolean;
  isGeneratingPr: boolean;
  commitAll: boolean;
  createPrDrafts: Record<string, CreatePrDraftValues>;
  activeCreatePrDraftKey: string | null;
}

interface GitInteractionActions {
  setCommitOpen: (open: boolean) => void;
  setPushOpen: (open: boolean) => void;
  setBranchOpen: (open: boolean) => void;
  setCommitMessage: (value: string) => void;
  setCommitNextStep: (value: CommitNextStep) => void;
  setPushMode: (value: PushMode) => void;
  setPushState: (value: PushState) => void;
  setPushError: (value: string | null) => void;
  setPrTitle: (value: string) => void;
  setPrBody: (value: string) => void;
  setCommitError: (value: string | null) => void;
  setBranchName: (value: string) => void;
  setBranchError: (value: string | null) => void;
  setIsSubmitting: (value: boolean) => void;
  setIsGeneratingCommitMessage: (value: boolean) => void;
  setIsGeneratingPr: (value: boolean) => void;
  setCommitAll: (value: boolean) => void;

  openCommit: (nextStep: CommitNextStep) => void;
  openPush: (mode: PushMode) => void;
  openCreatePr: (opts: {
    needsBranch: boolean;
    needsCommit: boolean;
    baseBranch: string | null;
    suggestedBranchName?: string;
    draftKey: string;
  }) => void;
  closeCreatePr: () => void;
  setCreatePrStep: (step: CreatePrStep) => void;
  setCreatePrError: (error: string | null) => void;
  setCreatePrDraft: (value: boolean) => void;
  setCreatePrFailedStep: (step: CreatePrStep | null) => void;
  clearCreatePrDraft: (key: string) => void;
  openBranch: (suggestedName?: string) => void;
  closeCommit: () => void;
  closePush: () => void;
  closeBranch: () => void;
}

export interface GitInteractionStore extends GitInteractionState {
  actions: GitInteractionActions;
}

const initialState: GitInteractionState = {
  commitOpen: false,
  pushOpen: false,
  createPrOpen: false,
  branchOpen: false,
  commitMessage: "",
  commitNextStep: "commit",
  pushMode: "push",
  pushState: "idle",
  pushError: null,
  prTitle: "",
  prBody: "",
  createPrStep: "idle",
  createPrError: null,
  createPrNeedsBranch: false,
  createPrNeedsCommit: false,
  createPrBaseBranch: null,
  createPrDraft: false,
  createPrFailedStep: null,
  commitError: null,
  branchName: "",
  branchError: null,
  isSubmitting: false,
  isGeneratingCommitMessage: false,
  isGeneratingPr: false,
  commitAll: true,
  createPrDrafts: {},
  activeCreatePrDraftKey: null,
};

function draftHasContent(draft: CreatePrDraftValues): boolean {
  return (
    draft.branchName !== "" ||
    draft.commitMessage !== "" ||
    draft.prTitle !== "" ||
    draft.prBody !== ""
  );
}

export const useGitInteractionStore = create<GitInteractionStore>()(
  persist(
    (set, get) => ({
      ...initialState,
      actions: {
        setCommitOpen: (open) => set({ commitOpen: open }),
        setPushOpen: (open) => set({ pushOpen: open }),
        setBranchOpen: (open) => set({ branchOpen: open }),
        setCommitMessage: (value) => set({ commitMessage: value }),
        setCommitNextStep: (value) => set({ commitNextStep: value }),
        setPushMode: (value) => set({ pushMode: value }),
        setPushState: (value) => set({ pushState: value }),
        setPushError: (value) => set({ pushError: value }),
        setPrTitle: (value) => set({ prTitle: value }),
        setPrBody: (value) => set({ prBody: value }),
        setCommitError: (value) => set({ commitError: value }),
        setBranchName: (value) => set({ branchName: value }),
        setBranchError: (value) => set({ branchError: value }),
        setIsSubmitting: (value) => set({ isSubmitting: value }),
        setIsGeneratingCommitMessage: (value) =>
          set({ isGeneratingCommitMessage: value }),
        setIsGeneratingPr: (value) => set({ isGeneratingPr: value }),
        setCommitAll: (value) => set({ commitAll: value }),

        openCommit: (nextStep) =>
          set({
            commitNextStep: nextStep,
            commitError: null,
            commitOpen: true,
          }),
        openPush: (mode) =>
          set({
            pushMode: mode,
            pushState: "idle",
            pushError: null,
            pushOpen: true,
          }),
        openCreatePr: ({
          needsBranch,
          needsCommit,
          baseBranch,
          suggestedBranchName,
          draftKey,
        }) => {
          const existingDraft = get().createPrDrafts[draftKey];
          const branchName = existingDraft?.branchName
            ? existingDraft.branchName
            : (suggestedBranchName ?? "");
          set({
            createPrOpen: true,
            createPrStep: "idle",
            createPrError: null,
            createPrNeedsBranch: needsBranch,
            createPrNeedsCommit: needsCommit,
            createPrBaseBranch: baseBranch,
            createPrDraft: false,
            createPrFailedStep: null,
            branchName,
            commitMessage: existingDraft?.commitMessage ?? "",
            prTitle: existingDraft?.prTitle ?? "",
            prBody: existingDraft?.prBody ?? "",
            isGeneratingCommitMessage: false,
            isGeneratingPr: false,
            isSubmitting: false,
            activeCreatePrDraftKey: draftKey,
          });
        },
        closeCreatePr: () => {
          const state = get();
          const key = state.activeCreatePrDraftKey;
          if (key === null) {
            set({ createPrOpen: false, isSubmitting: false });
            return;
          }
          const snapshot: CreatePrDraftValues = {
            branchName: state.branchName,
            commitMessage: state.commitMessage,
            prTitle: state.prTitle,
            prBody: state.prBody,
          };
          const nextDrafts = { ...state.createPrDrafts };
          if (draftHasContent(snapshot)) {
            nextDrafts[key] = snapshot;
          } else {
            delete nextDrafts[key];
          }
          set({
            createPrOpen: false,
            createPrDrafts: nextDrafts,
            activeCreatePrDraftKey: null,
            isSubmitting: false,
          });
        },
        setCreatePrStep: (step) => set({ createPrStep: step }),
        setCreatePrError: (error) => set({ createPrError: error }),
        setCreatePrDraft: (value) => set({ createPrDraft: value }),
        setCreatePrFailedStep: (step) => set({ createPrFailedStep: step }),
        clearCreatePrDraft: (key) => {
          const state = get();
          const nextDrafts = { ...state.createPrDrafts };
          delete nextDrafts[key];
          const nextActiveKey =
            state.activeCreatePrDraftKey === key
              ? null
              : state.activeCreatePrDraftKey;
          set({
            createPrDrafts: nextDrafts,
            activeCreatePrDraftKey: nextActiveKey,
          });
        },
        openBranch: (suggestedName) =>
          set({
            branchName: suggestedName ?? "",
            branchError: null,
            branchOpen: true,
          }),
        closeCommit: () => set({ commitOpen: false, commitError: null }),
        closePush: () =>
          set({
            pushOpen: false,
            pushState: "idle",
            pushError: null,
          }),
        closeBranch: () =>
          set({ branchOpen: false, branchError: null, branchName: "" }),
      },
    }),
    {
      name: "git-interaction-create-pr-drafts",
      storage: electronStorage,
      partialize: (state) => ({ createPrDrafts: state.createPrDrafts }),
    },
  ),
);

export function getGitInteractionActionLabel(
  actionId: GitMenuActionId,
): string {
  switch (actionId) {
    case "commit":
      return "Commit";
    case "push":
      return "Push";
    case "sync":
      return "Sync";
    case "publish":
      return "Publish Branch";
    case "create-pr":
      return "Create PR";
    case "view-pr":
      return "View PR";
    case "branch-here":
      return "New branch";
    default:
      return "Git Action";
  }
}
