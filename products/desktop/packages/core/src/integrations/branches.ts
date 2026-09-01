export interface GithubBranchesPage {
  branches: string[];
  defaultBranch: string | null;
  hasMore: boolean;
}

export const BRANCHES_FIRST_PAGE_SIZE = 50;
export const BRANCHES_PAGE_SIZE = 100;

export function branchPageSizeForOffset(offset: number): number {
  return offset === 0 ? BRANCHES_FIRST_PAGE_SIZE : BRANCHES_PAGE_SIZE;
}

export function computeNextBranchOffset(
  lastPage: GithubBranchesPage,
  allPages: ReadonlyArray<GithubBranchesPage>,
): number | undefined {
  if (!lastPage.hasMore) return undefined;
  return allPages.reduce((total, page) => total + page.branches.length, 0);
}

export interface FlattenedBranches {
  branches: string[];
  defaultBranch: string | null;
}

export function flattenBranchPages(
  pages: ReadonlyArray<GithubBranchesPage> | undefined,
): FlattenedBranches {
  if (!pages || !pages.length) {
    return { branches: [], defaultBranch: null };
  }
  return {
    branches: pages.flatMap((page) => page.branches),
    defaultBranch: pages[0]?.defaultBranch ?? null,
  };
}
