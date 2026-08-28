import type { AvailableCommand } from "@agentclientprotocol/sdk";
import {
  AI_FEEDBACK_TEXT_MAX_LENGTH,
  buildSlashFeedbackEvents,
} from "@posthog/core/analytics/aiFeedback";
import {
  basename,
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
    events: unknown[];
  } | null;
  taskRun: { id?: string } | null;
  /** Fires a "/btw" side question. Absent when the session doesn't support them. */
  /** Returns false when a side question is already pending for this run. */
  askSideQuestion?: (question: string) => boolean;
}

export interface CodeCommandInsertContext {
  editor: Editor;
  chipId: string;
  sessionId: string;
}

interface CodeCommand {
  name: string;
  description: string;
  /** `required` is the message shown when the command is sent without input.
   * `maxLength` bounds the input; over-limit submits are rejected pre-submit
   * so the composer keeps the text. */
  input?: { hint: string; required?: string; maxLength?: number };
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

const FEEDBACK_COMMENT_REQUIRED =
  "Add a comment after /feedback. To rate without a comment, use /good or /bad.";

function makeFeedbackCommand(
  name: string,
  feedbackType: FeedbackType,
  label: string,
  input: NonNullable<CodeCommand["input"]>,
): CodeCommand {
  return {
    name,
    description: `Capture ${label.toLowerCase()} feedback`,
    input: { ...input, maxLength: AI_FEEDBACK_TEXT_MAX_LENGTH },
    execute(args, ctx) {
      if (input.required && !args?.trim()) {
        toast.error(input.required);
        return;
      }
      const { metric, feedback } = buildSlashFeedbackEvents({
        run: {
          taskId: ctx.taskId,
          taskRunId: ctx.session?.taskRunId ?? ctx.taskRun?.id,
        },
        eventCount: ctx.session?.events.length ?? 0,
        feedbackType,
        comment: args,
      });
      if (metric) track(ANALYTICS_EVENTS.AI_METRIC, metric);
      if (feedback) track(ANALYTICS_EVENTS.AI_FEEDBACK, feedback);
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

export const BTW_COMMAND_NAME = "btw";

const btwCommand: CodeCommand = {
  name: BTW_COMMAND_NAME,
  description:
    "Ask a quick side question without interrupting the conversation",
  input: { hint: "your question", required: "Add a question after /btw" },
  execute(args, ctx) {
    const question = args?.trim();
    if (!question) {
      toast.error("Add a question after /btw");
      return;
    }
    if (!ctx.askSideQuestion) {
      toast.error("Side questions aren't supported for this session yet.");
      return;
    }
    if (!ctx.askSideQuestion(question)) {
      toast.error("Wait for your last side question to finish first");
    }
  },
};

const commands: CodeCommand[] = [
  addDirCommand,
  btwCommand,
  makeFeedbackCommand("good", "good", "Positive", {
    hint: "optional comment",
  }),
  makeFeedbackCommand("bad", "bad", "Negative", { hint: "optional comment" }),
  makeFeedbackCommand("feedback", "general", "General", {
    hint: "your comment",
    required: FEEDBACK_COMMENT_REQUIRED,
  }),
];

export const CODE_COMMANDS: AvailableCommand[] = commands.map((cmd) => ({
  name: cmd.name,
  description: cmd.description,
  input: cmd.input ? { hint: cmd.input.hint } : undefined,
}));

const commandMap = new Map(commands.map((cmd) => [cmd.name, cmd]));

export function getCodeCommand(name: string): CodeCommand | undefined {
  return commandMap.get(name);
}

/**
 * Message to show instead of sending, when `text` is a code command that
 * requires input and has none, or the input exceeds the command's limit.
 * Checked before submit so the composer keeps the text for the user to
 * complete or trim.
 */
export function getCodeCommandInputError(text: string): string | null {
  const parsed = parseCommandLine(text.trim());
  if (!parsed) return null;
  const input = commandMap.get(parsed.name)?.input;
  const args = parsed.args?.trim();
  if (input?.required && !args) {
    return input.required;
  }
  if (input?.maxLength && args && args.length > input.maxLength) {
    return `Your comment is ${args.length.toLocaleString()} characters and the limit is ${input.maxLength.toLocaleString()}. Shorten it and try again.`;
  }
  return null;
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
