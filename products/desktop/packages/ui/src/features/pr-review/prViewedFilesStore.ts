import type { ChangedFile } from "@posthog/shared/domain-types";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Cap on tracked PRs so the persisted map can't grow unboundedly. */
export const MAX_TRACKED_PRS = 50;

interface PrViewedEntry {
  /** Last write, used to evict the stalest PR past the cap. */
  updatedAt: number;
  /** filePath -> fingerprint of the diff when the file was marked viewed. */
  files: Record<string, string>;
}

interface PrViewedFilesState {
  viewedByPr: Record<string, PrViewedEntry>;
}

interface PrViewedFilesActions {
  markViewed: (prUrl: string, filePath: string, fingerprint: string) => void;
  unmarkViewed: (prUrl: string, filePath: string) => void;
}

type PrViewedFilesStore = PrViewedFilesState & PrViewedFilesActions;

/**
 * GitHub-style "Viewed" semantics: a file stays viewed only while its diff is
 * unchanged. The fingerprint captures the patch when the user checks the box;
 * if the PR gains commits that touch the file, the fingerprint stops matching
 * and the file drops back to unviewed — same behavior as github.com.
 */
export function fileViewedFingerprint(file: ChangedFile): string {
  const basis = `${file.status}:${
    file.patch ?? `${file.linesAdded ?? 0}/${file.linesRemoved ?? 0}`
  }`;
  // djb2 — cheap and stable; change detection only, not integrity.
  let hash = 5381;
  for (let i = 0; i < basis.length; i++) {
    hash = ((hash << 5) + hash + basis.charCodeAt(i)) | 0;
  }
  return String(hash >>> 0);
}

function evictStalest(
  viewedByPr: Record<string, PrViewedEntry>,
): Record<string, PrViewedEntry> {
  const urls = Object.keys(viewedByPr);
  if (urls.length <= MAX_TRACKED_PRS) return viewedByPr;
  let stalest: string | null = null;
  let stalestAt = Number.POSITIVE_INFINITY;
  for (const url of urls) {
    const at = viewedByPr[url]?.updatedAt ?? 0;
    if (at < stalestAt) {
      stalest = url;
      stalestAt = at;
    }
  }
  if (stalest === null) return viewedByPr;
  const next = { ...viewedByPr };
  delete next[stalest];
  return next;
}

export const usePrViewedFilesStore = create<PrViewedFilesStore>()(
  persist(
    (set) => ({
      viewedByPr: {},
      markViewed: (prUrl, filePath, fingerprint) =>
        set((state) => {
          const entry = state.viewedByPr[prUrl];
          const next: PrViewedEntry = {
            updatedAt: Date.now(),
            files: { ...entry?.files, [filePath]: fingerprint },
          };
          return {
            viewedByPr: evictStalest({
              ...state.viewedByPr,
              [prUrl]: next,
            }),
          };
        }),
      unmarkViewed: (prUrl, filePath) =>
        set((state) => {
          const entry = state.viewedByPr[prUrl];
          if (!entry || !(filePath in entry.files)) return state;
          const files = { ...entry.files };
          delete files[filePath];
          return {
            viewedByPr: {
              ...state.viewedByPr,
              [prUrl]: { updatedAt: Date.now(), files },
            },
          };
        }),
    }),
    { name: "pr-viewed-files" },
  ),
);

export function isFileViewed(
  viewedByPr: Record<string, PrViewedEntry>,
  prUrl: string,
  file: ChangedFile,
): boolean {
  return viewedByPr[prUrl]?.files[file.path] === fileViewedFingerprint(file);
}
