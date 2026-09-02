import {
  githubIssueToMentionChip,
  githubPullRequestToMentionChip,
} from "@posthog/core/message-editor/githubIssueChip";
import {
  getAbsolutePathSuggestion,
  mergeCommands,
  searchCommands,
  shapeCommandSuggestions,
  shapeFileSuggestions,
} from "@posthog/core/message-editor/suggestions";
import { sessionSupportsSideQuestion } from "@posthog/shared";
import {
  getAvailableCommandsForTask,
  useSessionStore,
} from "@posthog/ui/features/sessions/sessionStore";
import { fetchRepoFiles, searchFiles } from "../../repo-files/useRepoFiles";
import { BTW_COMMAND_NAME, CODE_COMMANDS } from "../commands";
import { useDraftStore } from "../draftStore";
import { searchGithubRefs } from "../hostApi";
import type {
  CommandSuggestionItem,
  FileSuggestionItem,
  IssueSuggestionItem,
} from "../types";

function getTaskCommandContext(taskId: string | undefined): {
  adapter: string | undefined;
  supportsSideQuestion: boolean;
  commands: ReturnType<typeof getAvailableCommandsForTask>;
} {
  if (!taskId)
    return { adapter: undefined, supportsSideQuestion: false, commands: null };
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  const session = taskRunId ? state.sessions[taskRunId] : undefined;
  return {
    adapter: session?.adapter,
    supportsSideQuestion: session
      ? sessionSupportsSideQuestion(session)
      : false,
    commands: getAvailableCommandsForTask(taskId),
  };
}

export async function getFileSuggestions(
  sessionId: string,
  query: string,
): Promise<FileSuggestionItem[]> {
  const repoPath = useDraftStore.getState().contexts[sessionId]?.repoPath;
  const absoluteMatch = getAbsolutePathSuggestion(query);

  if (!repoPath) {
    return absoluteMatch ? [absoluteMatch] : [];
  }

  const { files, fzf } = await fetchRepoFiles(repoPath, {
    includeDirectories: true,
  });
  const matched = searchFiles(fzf, files, query);

  return shapeFileSuggestions(matched, repoPath, absoluteMatch);
}

export async function getIssueSuggestions(
  sessionId: string,
  query: string,
): Promise<IssueSuggestionItem[]> {
  const repoPath = useDraftStore.getState().contexts[sessionId]?.repoPath;
  if (!repoPath) return [];

  try {
    const refs = await searchGithubRefs({
      directoryPath: repoPath,
      query: query || undefined,
      limit: 25,
    });

    return refs.map((ref) => {
      const chip =
        ref.kind === "pr"
          ? githubPullRequestToMentionChip(ref)
          : githubIssueToMentionChip(ref);
      return {
        id: chip.id,
        label: chip.label,
        chipType: chip.type,
        kind: ref.kind,
        number: ref.number,
        title: ref.title,
        url: ref.url,
        repo: ref.repo,
        state: ref.state,
        labels: ref.labels,
        isDraft: ref.isDraft,
      };
    });
  } catch {
    return [];
  }
}

export function getCommandSuggestions(
  sessionId: string,
  query: string,
): CommandSuggestionItem[] {
  const store = useDraftStore.getState();
  const taskId = store.contexts[sessionId]?.taskId;
  // Agent commands (from `available_commands_update`) are authoritative for
  // Claude once a session has reported them. Codex does not emit skill slash
  // commands, so keep merging the trpc-fetched skills fallback for GPT tasks.
  // `null` means "agent hasn't reported yet"; an empty array means "agent
  // reported empty".
  const {
    adapter,
    supportsSideQuestion,
    commands: sessionCommands,
  } = getTaskCommandContext(taskId);
  const draftCommands = store.commands[sessionId] ?? [];
  const localDraftCommands = draftCommands.filter((cmd) => cmd.localSkill);
  const agentCommands =
    sessionCommands === null
      ? draftCommands
      : adapter === "codex"
        ? mergeCommands(sessionCommands, draftCommands)
        : [...sessionCommands, ...localDraftCommands];
  // Only offer /btw where the session can actually answer a side question;
  // otherwise picking it from the menu dead-ends in an error toast. The
  // runtime guard in the command still stands for users who type /btw by hand.
  const codeCommands = supportsSideQuestion
    ? CODE_COMMANDS
    : CODE_COMMANDS.filter((cmd) => cmd.name !== BTW_COMMAND_NAME);
  const commands = mergeCommands(codeCommands, agentCommands);
  const filtered = searchCommands(commands, query);

  return shapeCommandSuggestions(filtered);
}
