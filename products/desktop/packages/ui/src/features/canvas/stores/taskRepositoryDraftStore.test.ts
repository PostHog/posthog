import { beforeEach, describe, expect, it } from "vitest";
import {
  resolveTaskRepositoryDraft,
  useTaskRepositoryDraftStore,
} from "./taskRepositoryDraftStore";

describe("taskRepositoryDraftStore", () => {
  beforeEach(() => {
    useTaskRepositoryDraftStore.setState({ drafts: {} });
  });

  it("falls back to the space defaults when no draft exists", () => {
    const resolved = resolveTaskRepositoryDraft(
      undefined,
      ["posthog/posthog"],
      7,
    );
    expect(resolved).toEqual({
      repositories: ["posthog/posthog"],
      githubIntegration: 7,
      folder: "",
    });
  });

  it("shares a draft set on one surface with every composer in the space", () => {
    const { setDraft } = useTaskRepositoryDraftStore.getState();
    setDraft("chan-1", {
      repositories: ["posthog/posthog-js"],
      githubIntegration: 3,
      folder: "",
    });

    const draft = useTaskRepositoryDraftStore.getState().drafts["chan-1"];
    expect(resolveTaskRepositoryDraft(draft, ["posthog/posthog"], 7)).toEqual({
      repositories: ["posthog/posthog-js"],
      githubIntegration: 3,
      folder: "",
    });
    expect(useTaskRepositoryDraftStore.getState().drafts["chan-2"]).toBe(
      undefined,
    );
  });

  it("falls back to the space defaults once the consumed draft is cleared", () => {
    const { setDraft, clearDraft } = useTaskRepositoryDraftStore.getState();
    setDraft("chan-1", {
      repositories: ["posthog/posthog-js"],
      githubIntegration: 3,
      folder: "",
    });
    clearDraft("chan-1");

    const draft = useTaskRepositoryDraftStore.getState().drafts["chan-1"];
    expect(resolveTaskRepositoryDraft(draft, ["posthog/posthog"], 7)).toEqual({
      repositories: ["posthog/posthog"],
      githubIntegration: 7,
      folder: "",
    });
  });

  it("keeps an emptied draft instead of backfilling from the defaults", () => {
    const resolved = resolveTaskRepositoryDraft(
      { repositories: [], githubIntegration: null, folder: "/tmp/work" },
      ["posthog/posthog"],
      7,
    );
    expect(resolved.repositories).toEqual([]);
    expect(resolved.githubIntegration).toBe(null);
    expect(resolved.folder).toBe("/tmp/work");
  });
});
