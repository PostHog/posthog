export interface RegisteredFolder {
  id: string;
  path: string;
  name: string;
  remoteUrl: string | null;
  lastAccessed: string;
  createdAt: string;
  /**
   * Root of the main checkout when this folder is a linked git worktree,
   * null for a main clone.
   */
  mainRepoPath?: string | null;
  exists?: boolean;
}
