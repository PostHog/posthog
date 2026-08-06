import type { AvailableCommand } from "@agentclientprotocol/sdk";
import {
  basename,
  buildFeedbackEventPayload,
  parseCommandLine,
} from "@posthog/core/message-editor/commands";
import { escapeXmlAttr, type SkillSource } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type FeedbackType,
} from "@posthog/shared/analytics-events";
import { useAddDirectoryDialogStore } from "@posthog/ui/features/folder-picker/addDirectoryDialogStore";
import { toast } from "@posthog/ui/primitives/toast";
import type { Editor } from "@tiptap/core";
import { track } from "../../shell/analytics";
import { selectDirectory } from "./hostApi";
import type { MentionChipAttrs } from "./tiptap/MentionChipNode";
import type { EditorAvailableCommand } from "./types";

interface CommandContext {
  taskId: string;
  repoPath: string | null | undefined;
  session: {
    taskRunId?: string;
    logUrl?: string;
    events: unknown[];
  } | null;
  taskRun: { id?: string; log_url?: string } | null;
}

export interface CodeCommandInsertContext {
  editor: Editor;
  chipId: string;
  sessionId: string;
}

interface CodeCommand {
  name: string;
  description: string;
  input?: { hint: string };
  /** Optional override for the chip attrs inserted when this command is committed. */
  placeholderChip?: Partial<MentionChipAttrs>;
  /** Fires immediately after the chip is inserted into the editor. */
  onInsert?: (ctx: CodeCommandInsertContext) => void;
  /** Runs at submission time when the message is sent. Optional. */
  execute?: (
    args: string | undefined,
    context: CommandContext,
  ) => Promise<void> | void;
}

function makeFeedbackCommand(
  name: string,
  feedbackType: FeedbackType,
  label: string,
): CodeCommand {
  return {
    name,
    description: `Capture ${label.toLowerCase()} feedback`,
    input: { hint: "optional comment" },
    execute(args, ctx) {
      track(
        ANALYTICS_EVENTS.TASK_FEEDBACK,
        buildFeedbackEventPayload({
          taskId: ctx.taskId,
          taskRunId: ctx.session?.taskRunId ?? ctx.taskRun?.id,
          logUrl: ctx.session?.logUrl ?? ctx.taskRun?.log_url,
          eventCount: ctx.session?.events.length ?? 0,
          feedbackType,
          comment: args,
        }),
      );
      toast.success(`${label} feedback captured`);
    },
  };
}

const addDirCommand: CodeCommand = {
  name: "add-dir",
  description: "Add a folder the agent can access in this task",
  async onInsert(ctx) {
    const taskId = ctx.sessionId;
    try {
      const path = await selectDirectory();
      if (!path) {
        ctx.editor.commands.removeMentionChipById(ctx.chipId);
        return;
      }
      ctx.editor.commands.replaceMentionChipById(ctx.chipId, {
        id: path,
        label: `add-dir - ${basename(path)}`,
      });
      useAddDirectoryDialogStore.getState().show({
        taskId,
        path,
        onCancel: () => ctx.editor.commands.removeMentionChipById(ctx.chipId),
      });
    } catch (err) {
      ctx.editor.commands.removeMentionChipById(ctx.chipId);
      toast.error("Failed to open folder picker", {
        description: err instanceof Error ? err.message : String(err),
      });
    }
  },
};

const commands: CodeCommand[] = [
  addDirCommand,
  makeFeedbackCommand("good", "good", "Positive"),
  makeFeedbackCommand("bad", "bad", "Negative"),
  makeFeedbackCommand("feedback", "general", "General"),
];

export const CODE_COMMANDS: AvailableCommand[] = commands.map((cmd) => ({
  name: cmd.name,
  description: cmd.description,
  input: cmd.input,
}));

const commandMap = new Map(commands.map((cmd) => [cmd.name, cmd]));

export function getCodeCommand(name: string): CodeCommand | undefined {
  return commandMap.get(name);
}

export async function tryExecuteCodeCommand(
  text: string,
  context: CommandContext,
): Promise<boolean> {
  const parsed = parseCommandLine(text);
  if (!parsed) return false;

  const cmd = commandMap.get(parsed.name);
  if (!cmd?.execute) return false;

  await cmd.execute(parsed.args, context);
  return true;
}

export function rewriteLocalSkillCommandPrompt(
  text: string,
  commands: EditorAvailableCommand[],
): string | null {
  const parsed = parseCommandLine(text.trim());
  if (!parsed) return null;

  const localSkill = commands.find(
    (cmd) => cmd.name === parsed.name,
  )?.localSkill;
  if (!localSkill) return null;

  const skillTag = `<skill name="${escapeXmlAttr(localSkill.name)}" source="${escapeXmlAttr(localSkill.source)}" path="${escapeXmlAttr(localSkill.path)}" />`;
  return parsed.args?.trim() ? `${skillTag} ${parsed.args}` : skillTag;
}

interface LocalSkillListEntry {
  name: string;
  description: string;
  source: SkillSource;
  path: string;
}

export function skillToEditorCommand(
  skill: LocalSkillListEntry,
): EditorAvailableCommand {
  return {
    name: skill.name,
    description: skill.description,
    ...(skill.source === "bundled"
      ? {}
      : {
          localSkill: {
            name: skill.name,
            source: skill.source,
            path: skill.path,
          },
        }),
  };
}

export async function resolveLocalSkillPrompt(
  text: string,
  listSkills: () => Promise<LocalSkillListEntry[]>,
): Promise<string | null> {
  if (!text.trim().startsWith("/")) return null;
  const skills = await listSkills();
  return rewriteLocalSkillCommandPrompt(text, skills.map(skillToEditorCommand));
}
