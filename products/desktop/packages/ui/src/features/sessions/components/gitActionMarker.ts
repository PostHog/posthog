export type GitActionType =
  | "commit-push"
  | "publish"
  | "push"
  | "pull"
  | "sync"
  | "create-pr";

const GIT_ACTION_MARKER_PREFIX = "<!-- GIT_ACTION:";
const GIT_ACTION_MARKER_SUFFIX = " -->";

export function parseGitActionMessage(content: string): {
  isGitAction: boolean;
  actionType: GitActionType | null;
  prompt: string;
} {
  if (!content.startsWith(GIT_ACTION_MARKER_PREFIX)) {
    return { isGitAction: false, actionType: null, prompt: content };
  }

  const markerEnd = content.indexOf(GIT_ACTION_MARKER_SUFFIX);
  if (markerEnd === -1) {
    return { isGitAction: false, actionType: null, prompt: content };
  }

  const actionType = content.slice(
    GIT_ACTION_MARKER_PREFIX.length,
    markerEnd,
  ) as GitActionType;

  const prompt = content.slice(markerEnd + GIT_ACTION_MARKER_SUFFIX.length + 1); // +1 for newline

  return { isGitAction: true, actionType, prompt };
}
