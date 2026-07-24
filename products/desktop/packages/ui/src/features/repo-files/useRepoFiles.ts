import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { useHostTRPC } from "@posthog/host-router/react";
import type { HostRouter } from "@posthog/host-router/router";
import type { MentionItem } from "@posthog/shared/domain-types";
import { useQuery } from "@tanstack/react-query";
import {
  createTRPCOptionsProxy,
  type TRPCOptionsProxy,
} from "@trpc/tanstack-react-query";
import { byLengthAsc, Fzf } from "fzf";
import { useMemo } from "react";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";

export interface FileItem {
  path: string;
  name: string;
  dir: string;
  kind: "file" | "directory";
  /** Precomputed lowercase path/name so search doesn't re-lowercase per query. */
  lowerPath?: string;
  lowerName?: string;
}

const MENTION_DISPLAY_LIMIT = 20;

export function pathToFileItem(path: string): FileItem {
  const parts = path.split("/");
  const name = parts.pop() ?? path;
  const dir = parts.join("/");
  return {
    path,
    name,
    dir,
    kind: "file",
    lowerPath: path.toLowerCase(),
    lowerName: name.toLowerCase(),
  };
}

function pathToFolderItem(path: string): FileItem {
  const parts = path.split("/");
  const name = parts.pop() ?? path;
  const dir = parts.join("/");
  return {
    path,
    name,
    dir,
    kind: "directory",
    lowerPath: path.toLowerCase(),
    lowerName: name.toLowerCase(),
  };
}

export function transformRawFiles(
  rawFiles: MentionItem[],
  includeDirectories: boolean,
): FileItem[] {
  return rawFiles
    .filter((file): file is MentionItem & { path: string } => !!file.path)
    .filter((file) => includeDirectories || file.kind !== "directory")
    .map((file) =>
      file.kind === "directory"
        ? pathToFolderItem(file.path)
        : pathToFileItem(file.path),
    );
}

export function createFzf(files: FileItem[]): Fzf<FileItem[]> {
  return new Fzf(files, {
    selector: (item) =>
      item.kind === "directory"
        ? `${item.name}/ ${item.path}/`
        : `${item.name} ${item.path}`,
    limit: MENTION_DISPLAY_LIMIT,
    tiebreakers: [byLengthAsc],
  });
}

export function useRepoFiles(
  repoPath: string | undefined,
  enabled = true,
  options: { includeDirectories?: boolean } = {},
) {
  const { includeDirectories = false } = options;
  const trpc = useHostTRPC();
  const { data: rawFiles, isLoading } = useQuery({
    ...trpc.fs.listRepoFiles.queryOptions({ repoPath: repoPath ?? "" }),
    enabled: enabled && !!repoPath,
  });

  const files: FileItem[] = useMemo(() => {
    if (!rawFiles) return [];
    return transformRawFiles(rawFiles, includeDirectories);
  }, [rawFiles, includeDirectories]);

  const fzf = useMemo(() => createFzf(files), [files]);

  return { files, fzf, isLoading };
}

export function searchFiles(
  fzf: Fzf<FileItem[]>,
  files: FileItem[],
  query: string,
): FileItem[] {
  if (!query.trim()) {
    return files.slice(0, MENTION_DISPLAY_LIMIT);
  }
  const results = fzf.find(query);
  return results.map((result) => result.item);
}

export const MAX_FILE_RESULTS = 50;

/** Ranks files whose path contains every query term (split on spaces and "/"). */
export function rankFiles(files: FileItem[], query: string): FileItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return files.slice(0, MAX_FILE_RESULTS);
  const terms = q.split(/[\s/]+/).filter(Boolean);
  const lastTerm = terms[terms.length - 1];
  const matches: { file: FileItem; score: number }[] = [];
  for (const file of files) {
    const path = file.lowerPath ?? file.path.toLowerCase();
    if (!terms.every((t) => path.includes(t))) continue;
    const name = file.lowerName ?? file.name.toLowerCase();
    const nameHits = terms.filter((t) => name.includes(t)).length;
    const startsWithLast = name.startsWith(lastTerm) ? 1 : 0;
    matches.push({
      file,
      score: nameHits * 1000 + startsWithLast * 500 - path.length,
    });
  }
  matches.sort((a, b) => b.score - a.score);
  return matches.slice(0, MAX_FILE_RESULTS).map((m) => m.file);
}

export interface FileSection {
  label?: string;
  items: FileItem[];
}

/** Empty-query sections: "Recent" then "Other files" (or one unlabeled group). */
export function buildRecentFileSections(
  files: FileItem[],
  recentPaths: string[],
  limit: number,
): FileSection[] {
  if (recentPaths.length === 0) {
    return [{ items: files.slice(0, limit) }];
  }
  const recentSet = new Set(recentPaths);
  const recentItems = recentPaths.map(pathToFileItem);
  const rest = files
    .filter((f) => !recentSet.has(f.path))
    .slice(0, Math.max(0, limit - recentItems.length));
  return [
    { label: "Recent", items: recentItems },
    { label: "Other files", items: rest },
  ];
}

const fzfCache = new Map<
  string,
  { fzf: Fzf<FileItem[]>; filesLength: number }
>();

function fzfCacheKey(repoPath: string, includeDirectories: boolean): string {
  return `${repoPath} ${includeDirectories ? "1" : "0"}`;
}

let optionsProxy: TRPCOptionsProxy<HostRouter> | null = null;

function repoFilesQueryOptions(repoPath: string) {
  if (!optionsProxy) {
    optionsProxy = createTRPCOptionsProxy<HostRouter>({
      client: resolveService<HostTrpcClient>(HOST_TRPC_CLIENT),
      queryClient: resolveService<ImperativeQueryClient>(
        IMPERATIVE_QUERY_CLIENT,
      ),
    });
  }
  return optionsProxy.fs.listRepoFiles.queryOptions({ repoPath });
}

export async function fetchRepoFiles(
  repoPath: string,
  options: { includeDirectories?: boolean } = {},
): Promise<{ files: FileItem[]; fzf: Fzf<FileItem[]> }> {
  const { includeDirectories = false } = options;
  const queryClient = resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  );
  const rawFiles = await queryClient.fetchQuery({
    ...repoFilesQueryOptions(repoPath),
    staleTime: 1000 * 60 * 5,
  });

  const files = transformRawFiles(
    rawFiles as MentionItem[],
    includeDirectories,
  );

  const cacheKey = fzfCacheKey(repoPath, includeDirectories);
  const cached = fzfCache.get(cacheKey);
  if (cached && cached.filesLength === files.length) {
    return { files, fzf: cached.fzf };
  }

  const fzf = createFzf(files);
  fzfCache.set(cacheKey, { fzf, filesLength: files.length });
  return { files, fzf };
}
