import type { ChangedFile } from "@posthog/shared/domain-types";
import { beforeEach, describe, expect, it } from "vitest";
import {
  fileViewedFingerprint,
  isFileViewed,
  MAX_TRACKED_PRS,
  usePrViewedFilesStore,
} from "./prViewedFilesStore";

const PR_URL = "https://github.com/posthog/code/pull/123";

function file(overrides: Partial<ChangedFile> = {}): ChangedFile {
  return {
    path: "src/a.ts",
    status: "modified",
    patch: "@@ -1 +1 @@\n-old\n+new",
    ...overrides,
  };
}

describe("prViewedFilesStore", () => {
  beforeEach(() => {
    usePrViewedFilesStore.setState({ viewedByPr: {} });
  });

  it("marks a file viewed and reads it back", () => {
    const f = file();
    usePrViewedFilesStore
      .getState()
      .markViewed(PR_URL, f.path, fileViewedFingerprint(f));

    const { viewedByPr } = usePrViewedFilesStore.getState();
    expect(isFileViewed(viewedByPr, PR_URL, f)).toBe(true);
    expect(isFileViewed(viewedByPr, "https://other", f)).toBe(false);
  });

  it("drops viewed state when the file's diff changes", () => {
    const f = file();
    usePrViewedFilesStore
      .getState()
      .markViewed(PR_URL, f.path, fileViewedFingerprint(f));

    const changed = file({ patch: "@@ -1 +1 @@\n-old\n+newer" });
    const { viewedByPr } = usePrViewedFilesStore.getState();
    expect(isFileViewed(viewedByPr, PR_URL, changed)).toBe(false);
  });

  it("unmarks a viewed file", () => {
    const f = file();
    const store = usePrViewedFilesStore.getState();
    store.markViewed(PR_URL, f.path, fileViewedFingerprint(f));
    usePrViewedFilesStore.getState().unmarkViewed(PR_URL, f.path);

    const { viewedByPr } = usePrViewedFilesStore.getState();
    expect(isFileViewed(viewedByPr, PR_URL, f)).toBe(false);
  });

  it.each([
    ["status change", file({ status: "deleted" })],
    ["patch change", file({ patch: "@@ -2 +2 @@\n-x\n+y" })],
    [
      "line-count change on a patch-less file",
      file({ patch: undefined, linesAdded: 3, linesRemoved: 1 }),
    ],
  ])("fingerprint differs on %s", (_label, changed) => {
    expect(fileViewedFingerprint(changed)).not.toBe(
      fileViewedFingerprint(file()),
    );
  });

  it("evicts the stalest PR beyond the cap", () => {
    const f = file();
    const fingerprint = fileViewedFingerprint(f);
    for (let i = 0; i < MAX_TRACKED_PRS + 1; i++) {
      usePrViewedFilesStore
        .getState()
        .markViewed(`https://github.com/o/r/pull/${i}`, f.path, fingerprint);
    }

    const { viewedByPr } = usePrViewedFilesStore.getState();
    expect(Object.keys(viewedByPr)).toHaveLength(MAX_TRACKED_PRS);
    expect(viewedByPr["https://github.com/o/r/pull/0"]).toBeUndefined();
    expect(
      viewedByPr[`https://github.com/o/r/pull/${MAX_TRACKED_PRS}`],
    ).toBeDefined();
  });
});
