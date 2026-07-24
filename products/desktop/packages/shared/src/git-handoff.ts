export interface HandoffLocalGitState {
  head: string | null;
  branch: string | null;
  upstreamHead: string | null;
  upstreamRemote: string | null;
  upstreamMergeRef: string | null;
}

export interface GitHandoffCheckpoint {
  checkpointId: string;
  commit: string;
  checkpointRef: string;
  headRef?: string;
  head: string | null;
  branch: string | null;
  indexTree: string;
  worktreeTree: string;
  timestamp: string;
  upstreamRemote: string | null;
  upstreamMergeRef: string | null;
  remoteUrl: string | null;
}
