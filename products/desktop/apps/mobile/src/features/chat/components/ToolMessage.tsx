import { useRouter } from "expo-router";
import {
  ArrowsClockwise,
  Brain,
  FileText,
  GitBranch,
  Globe,
  type IconProps,
  ListChecks,
  MagnifyingGlass,
  PencilSimple,
  Play,
  Terminal,
  Trash,
  Wrench,
} from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import {
  formatPosthogExecBody,
  getPostHogExecDisplay,
  isPostHogExecTool,
} from "@/features/chat/utils/posthogExecDisplay";
import { McpAppHost } from "@/features/mcp/components/McpAppHost";
import { isMcpToolName } from "@/features/mcp/utils/mcpToolName";
import {
  getColorForClass,
  highlightCode,
  languageFromPath,
} from "@/lib/syntax-highlight";
import { useThemeColors } from "@/lib/theme";

export type ToolStatus = "pending" | "running" | "completed" | "error";
export type ToolKind =
  | "read"
  | "edit"
  | "delete"
  | "move"
  | "search"
  | "execute"
  | "think"
  | "fetch"
  | "switch_mode"
  | "create_task"
  | "other";

type PhosphorIcon = React.ComponentType<IconProps>;

const kindIcons: Record<ToolKind, PhosphorIcon> = {
  read: FileText,
  edit: PencilSimple,
  delete: Trash,
  move: FileText,
  search: MagnifyingGlass,
  execute: Terminal,
  think: Brain,
  fetch: Globe,
  switch_mode: ArrowsClockwise,
  create_task: ListChecks,
  other: Wrench,
};

const POSTHOG_EXEC_INPUT_PREVIEW_MAX_LENGTH = 120;

export function deriveToolKind(toolName: string): ToolKind {
  // Agent titles can include file paths, e.g. "Edit `src/foo.ts`" or
  // "Read 200 lines in `bar.ts`", so match on prefix / keyword.
  const name = toolName.toLowerCase();
  if (name.startsWith("read") || name === "read_file") return "read";
  if (
    name.startsWith("edit") ||
    name.startsWith("write") ||
    name.startsWith("multiedit") ||
    name.startsWith("multi_edit") ||
    name === "search_replace"
  )
    return "edit";
  if (name.startsWith("delete")) return "delete";
  if (
    name.startsWith("grep") ||
    name.startsWith("search") ||
    name.startsWith("glob") ||
    name.startsWith("find") ||
    name.startsWith("list")
  )
    return "search";
  if (
    name.startsWith("bash") ||
    name.startsWith("execute") ||
    name.startsWith("terminal")
  )
    return "execute";
  if (name.startsWith("think")) return "think";
  if (name.startsWith("webfetch") || name.startsWith("fetch")) return "fetch";
  if (name === "create_task") return "create_task";
  return "other";
}

export function getToolSubtitle(
  toolName: string,
  args?: Record<string, unknown>,
): string | null {
  if (!args) return null;
  const kind = deriveToolKind(toolName);

  switch (kind) {
    case "read":
    case "edit":
    case "delete":
    case "move":
      if (typeof args.file_path === "string")
        return shortenPath(args.file_path);
      if (typeof args.target_file === "string")
        return shortenPath(args.target_file);
      return null;
    case "search":
      if (typeof args.pattern === "string") return `"${args.pattern}"`;
      return null;
    case "execute":
      if (typeof args.command === "string")
        return args.command.length > 60
          ? `${args.command.slice(0, 60)}...`
          : args.command;
      return null;
    case "fetch":
      if (typeof args.url === "string")
        return args.url.length > 60 ? `${args.url.slice(0, 60)}...` : args.url;
      return null;
    case "think":
      if (typeof args.content === "string")
        return args.content.length > 60
          ? `${args.content.slice(0, 60)}...`
          : args.content;
      return null;
    default:
      return null;
  }
}

interface CreateTaskArgs {
  title?: string;
  description?: string;
  repository?: string;
}

export interface ToolMessageProps {
  toolName: string;
  rawToolName?: string;
  kind?: ToolKind;
  status: ToolStatus;
  args?: Record<string, unknown>;
  result?: unknown;
  hasHumanMessageAfter?: boolean;
  onOpenTask?: (taskId: string) => void;
}

export function formatToolTitle(
  toolName: string,
  args?: Record<string, unknown>,
): string {
  if (!args) return toolName;

  // Format common tool patterns like the desktop app
  if (toolName.toLowerCase() === "grep" && args.pattern) {
    return `grep "${args.pattern}"`;
  }
  if (toolName.toLowerCase() === "read_file" && args.target_file) {
    return "Read File";
  }
  if (toolName.toLowerCase() === "write" && args.file_path) {
    return "Write File";
  }
  if (toolName.toLowerCase() === "search_replace") {
    return "Search Replace";
  }

  return toolName;
}

// Shape guards for file-editing tool args. The agent forwards Claude's raw
// tool input through the ACP `rawInput` field, so we can detect Edit / Write /
// MultiEdit by the keys present in args.
interface EditArgs {
  file_path: string;
  old_string: string;
  new_string: string;
}

interface MultiEditArgs {
  file_path: string;
  edits: Array<{ old_string: string; new_string: string }>;
}

interface WriteArgs {
  file_path: string;
  content: string;
}

function asEditArgs(
  args: Record<string, unknown> | undefined,
): EditArgs | null {
  if (!args) return null;
  if (
    typeof args.file_path === "string" &&
    typeof args.old_string === "string" &&
    typeof args.new_string === "string"
  ) {
    return {
      file_path: args.file_path,
      old_string: args.old_string,
      new_string: args.new_string,
    };
  }
  return null;
}

function asMultiEditArgs(
  args: Record<string, unknown> | undefined,
): MultiEditArgs | null {
  if (!args || typeof args.file_path !== "string") return null;
  if (!Array.isArray(args.edits)) return null;
  const edits: MultiEditArgs["edits"] = [];
  for (const raw of args.edits) {
    if (
      raw &&
      typeof raw === "object" &&
      typeof (raw as Record<string, unknown>).old_string === "string" &&
      typeof (raw as Record<string, unknown>).new_string === "string"
    ) {
      edits.push({
        old_string: (raw as Record<string, unknown>).old_string as string,
        new_string: (raw as Record<string, unknown>).new_string as string,
      });
    }
  }
  if (edits.length === 0) return null;
  return { file_path: args.file_path, edits };
}

function asWriteArgs(
  args: Record<string, unknown> | undefined,
): WriteArgs | null {
  if (!args) return null;
  if (
    typeof args.file_path === "string" &&
    typeof args.content === "string" &&
    args.old_string === undefined
  ) {
    return { file_path: args.file_path, content: args.content };
  }
  return null;
}

// Strip ANSI escape codes from terminal output
function stripAnsi(text: string): string {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: stripping ANSI codes requires matching control chars
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");
}

function extractResultText(result: unknown): string | null {
  if (typeof result === "string") return result;
  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;
    for (const key of ["stdout", "output", "text", "content"] as const) {
      if (typeof obj[key] === "string") return obj[key] as string;
    }
  }
  return null;
}

function countDiffLines(
  editArgs: EditArgs | null,
  multiEditArgs: MultiEditArgs | null,
  writeArgs: WriteArgs | null,
): { added: number; removed: number } {
  let added = 0;
  let removed = 0;

  const countFromDiff = (oldText: string, newText: string) => {
    const lines = computeLineDiff(oldText, newText, Number.MAX_SAFE_INTEGER);
    for (const line of lines) {
      if (line.kind === "added") added++;
      else if (line.kind === "removed") removed++;
    }
  };

  if (editArgs) {
    countFromDiff(editArgs.old_string ?? "", editArgs.new_string ?? "");
  } else if (multiEditArgs) {
    for (const edit of multiEditArgs.edits) {
      countFromDiff(edit.old_string ?? "", edit.new_string ?? "");
    }
  } else if (writeArgs) {
    added = writeArgs.content ? writeArgs.content.split("\n").length : 0;
  }

  return { added, removed };
}

// Extract a file path from agent tool titles like "Read `src/foo.ts`" or
// "Read 200 lines in `bar.ts`" when rawInput/args are unavailable.
function extractPathFromTitle(title: string): string | null {
  const backtickMatch = title.match(/`([^`]+)`/);
  if (backtickMatch) return backtickMatch[1];
  // Fallback: strip common prefixes like "Read file", "Read 200 lines in"
  const stripped = title
    .replace(/^read\s+/i, "")
    .replace(/^file\s*/i, "")
    .replace(/^\d+\s+lines?\s+in\s+/i, "")
    .trim();
  // Only treat the remainder as a path if it looks like one
  if (stripped.includes("/") || stripped.includes(".")) return stripped;
  return null;
}

function shortenPath(path: string, maxLen = 48): string {
  if (path.length <= maxLen) return path;
  const parts = path.split("/");
  if (parts.length <= 2) return `…${path.slice(-(maxLen - 1))}`;
  return `…/${parts.slice(-2).join("/")}`;
}

function truncateText(text: string, maxLen: number): string {
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text;
}

// Unified diff support — detects and renders `git diff` output when the agent
// runs commands like `git diff` through the Bash tool and the result comes
// back as stdout rather than a structured tool content block.
type UnifiedDiffLine =
  | { kind: "file"; text: string }
  | { kind: "hunk"; text: string }
  | { kind: "added"; text: string }
  | { kind: "removed"; text: string }
  | { kind: "context"; text: string }
  | { kind: "meta"; text: string };

function looksLikeUnifiedDiff(text: string): boolean {
  if (!text) return false;
  if (/(^|\n)diff --git /.test(text)) return true;
  return /(^|\n)--- /.test(text) && /(^|\n)\+\+\+ /.test(text);
}

function extractDiffFromResult(result: unknown): string | null {
  if (typeof result === "string") {
    return looksLikeUnifiedDiff(result) ? result : null;
  }
  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;
    for (const key of ["stdout", "output", "text", "content"] as const) {
      const value = obj[key];
      if (typeof value === "string" && looksLikeUnifiedDiff(value)) {
        return value;
      }
    }
  }
  return null;
}

function parseUnifiedDiff(text: string): UnifiedDiffLine[] {
  const result: UnifiedDiffLine[] = [];
  for (const line of text.split("\n")) {
    if (
      line.startsWith("diff --git ") ||
      line.startsWith("--- ") ||
      line.startsWith("+++ ") ||
      line.startsWith("index ") ||
      line.startsWith("new file mode") ||
      line.startsWith("deleted file mode") ||
      line.startsWith("similarity index") ||
      line.startsWith("rename ")
    ) {
      result.push({ kind: "file", text: line });
    } else if (line.startsWith("@@")) {
      result.push({ kind: "hunk", text: line });
    } else if (line.startsWith("+")) {
      result.push({ kind: "added", text: line });
    } else if (line.startsWith("-")) {
      result.push({ kind: "removed", text: line });
    } else if (line.startsWith(" ")) {
      result.push({ kind: "context", text: line });
    } else {
      result.push({ kind: "meta", text: line });
    }
  }
  return result;
}

interface UnifiedDiffBlockProps {
  diffText: string;
  maxLines?: number;
}

function UnifiedDiffBlock({ diffText, maxLines = 120 }: UnifiedDiffBlockProps) {
  const allLines = parseUnifiedDiff(diffText);
  const truncated = allLines.length > maxLines;
  const lines = truncated ? allLines.slice(0, maxLines) : allLines;

  return (
    <View className="mt-1.5 overflow-hidden rounded-md border border-gray-6 bg-gray-2">
      {lines.map((line, i) => {
        let cls = "font-mono text-[11px] leading-4 text-gray-11 px-2";
        if (line.kind === "file") {
          cls += " text-gray-9";
        } else if (line.kind === "hunk") {
          cls += " bg-accent-3 text-accent-11";
        } else if (line.kind === "added") {
          cls += " bg-status-success/10 text-status-success";
        } else if (line.kind === "removed") {
          cls += " bg-status-error/10 text-status-error";
        } else if (line.kind === "context") {
          cls += " text-gray-11";
        } else {
          cls += " text-gray-9";
        }
        return (
          <Text key={`${i}-${line.kind}`} className={cls} selectable>
            {line.text || " "}
          </Text>
        );
      })}
      {truncated && (
        <Text className="px-2 py-1 font-mono text-[11px] text-gray-9 italic">
          … {allLines.length - maxLines} more lines
        </Text>
      )}
    </View>
  );
}

// LCS-based line diff: correctly identifies unchanged lines even when
// changes are scattered throughout the block, then collapses distant
// context into separators.
type DiffLine =
  | { kind: "context"; text: string }
  | { kind: "added"; text: string }
  | { kind: "removed"; text: string }
  | { kind: "separator" };

// O(n*m) LCS — fine for typical edit blocks (< 200 lines).
function lcsBacktrack(a: string[], b: string[]): DiffLine[] {
  const m = a.length;
  const n = b.length;

  // Build LCS table
  const dp: number[][] = [];
  for (let i = 0; i <= m; i++) {
    dp[i] = new Array(n + 1).fill(0);
  }
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }

  // Backtrack to produce diff
  const result: DiffLine[] = [];
  let i = m;
  let j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      result.push({ kind: "context", text: a[i - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.push({ kind: "added", text: b[j - 1] });
      j--;
    } else {
      result.push({ kind: "removed", text: a[i - 1] });
      i--;
    }
  }
  result.reverse();
  return result;
}

// Collapse context lines far from changes into separators.
function collapseContext(lines: DiffLine[], contextLines: number): DiffLine[] {
  // Mark which lines are near a change
  const isChange = lines.map((l) => l.kind === "added" || l.kind === "removed");
  const nearChange = new Array(lines.length).fill(false);
  for (let i = 0; i < lines.length; i++) {
    if (isChange[i]) {
      for (
        let k = Math.max(0, i - contextLines);
        k <= Math.min(lines.length - 1, i + contextLines);
        k++
      ) {
        nearChange[k] = true;
      }
    }
  }

  const result: DiffLine[] = [];
  let inSkip = false;
  for (let i = 0; i < lines.length; i++) {
    if (nearChange[i] || isChange[i]) {
      inSkip = false;
      result.push(lines[i]);
    } else if (!inSkip) {
      inSkip = true;
      result.push({ kind: "separator" });
    }
  }
  return result;
}

function computeLineDiff(
  oldText: string,
  newText: string,
  contextLines = 2,
): DiffLine[] {
  const oldLines = oldText.length > 0 ? oldText.split("\n") : [];
  const newLines = newText.length > 0 ? newText.split("\n") : [];

  if (oldLines.length === 0) {
    return newLines.map((l) => ({ kind: "added" as const, text: l }));
  }
  if (newLines.length === 0) {
    return oldLines.map((l) => ({ kind: "removed" as const, text: l }));
  }

  const raw = lcsBacktrack(oldLines, newLines);
  return collapseContext(raw, contextLines);
}

interface DiffBlockProps {
  oldText: string;
  newText: string;
  language?: string | null;
  maxLines?: number;
}

function HighlightedDiffLine({
  text,
  language,
  fallbackColor,
}: {
  text: string;
  language?: string | null;
  fallbackColor: string;
}) {
  const segments = useMemo(
    () => (language ? highlightCode(text, language) : null),
    [text, language],
  );

  if (!segments) {
    return <>{text || " "}</>;
  }

  return (
    <>
      {segments.map((seg, i) => {
        const color = getColorForClass(seg.className);
        return (
          <Text
            key={`h-${i}-${seg.className ?? "p"}`}
            style={{ color: color ?? fallbackColor }}
          >
            {seg.text}
          </Text>
        );
      })}
    </>
  );
}

function DiffBlock({
  oldText,
  newText,
  language,
  maxLines = 60,
}: DiffBlockProps) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  const allLines = computeLineDiff(oldText, newText);
  const truncated = !expanded && allLines.length > maxLines;
  const lines = truncated ? allLines.slice(0, maxLines) : allLines;

  return (
    <View className="mt-1.5 overflow-hidden rounded-md border border-gray-6 bg-gray-2">
      {lines.map((line, i) => {
        const key = `${line.kind}-${i}`;
        if (line.kind === "separator") {
          return (
            <Text
              key={key}
              className="px-2 font-mono text-[11px] text-gray-8 leading-4"
            >
              ···
            </Text>
          );
        }
        let cls = "font-mono text-[11px] leading-4 px-2";
        const fallbackColor =
          line.kind === "added"
            ? themeColors.status.success
            : line.kind === "removed"
              ? themeColors.status.error
              : themeColors.gray[11];
        if (line.kind === "added") {
          cls += " bg-status-success/10";
        } else if (line.kind === "removed") {
          cls += " bg-status-error/10";
        }
        const prefix =
          line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  ";
        return (
          <Text key={key} className={cls} selectable>
            <Text style={{ color: fallbackColor }}>{prefix}</Text>
            <HighlightedDiffLine
              text={line.text}
              language={language}
              fallbackColor={fallbackColor}
            />
          </Text>
        );
      })}
      {truncated && (
        <Pressable onPress={() => setExpanded(true)}>
          <Text className="px-2 py-1.5 font-mono text-[11px] text-accent-11">
            Show all {allLines.length} lines
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function CreateTaskPreview({
  args,
  showAction,
  onOpenTask,
}: {
  args: CreateTaskArgs;
  showAction: boolean;
  onOpenTask?: (taskId: string) => void;
}) {
  const router = useRouter();
  const themeColors = useThemeColors();
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRunTask = async () => {
    if (!args.description) return;

    setIsRunning(true);
    setError(null);

    try {
      // Dynamic import to avoid circular dependency
      const { createTask, runTaskInCloud } = await import("../../tasks/api");

      const task = await createTask({
        title: args.title,
        description: args.description,
        repository: args.repository,
      });

      await runTaskInCloud(task.id);

      if (onOpenTask) {
        onOpenTask(task.id);
      } else {
        router.push(`/task/${task.id}`);
      }
    } catch (err) {
      console.error("Failed to create/run task:", err);
      setError(err instanceof Error ? err.message : "Failed to run task");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <View className="mt-2 overflow-hidden rounded-lg border border-gray-7 bg-gray-3">
      {/* Header */}
      <View className="flex-row items-center gap-2 border-gray-7 border-b px-3 py-2">
        <ListChecks size={14} color={themeColors.accent[9]} />
        <Text className="font-mono text-[12px] text-gray-11">New task</Text>
      </View>

      {/* Content */}
      <View className="px-3 py-3">
        {/* Title */}
        {args.title && (
          <Text className="mb-2 font-medium text-[14px] text-gray-12">
            {args.title}
          </Text>
        )}

        {/* Description */}
        {args.description && (
          <Text
            className="mb-3 text-[13px] text-gray-11 leading-5"
            numberOfLines={4}
          >
            {args.description}
          </Text>
        )}

        {/* Repository */}
        {args.repository && (
          <View
            className={
              showAction
                ? "mb-3 flex-row items-center gap-1.5"
                : "flex-row items-center gap-1.5"
            }
          >
            <GitBranch size={12} color={themeColors.gray[9]} />
            <Text className="font-mono text-[12px] text-gray-9">
              {args.repository}
            </Text>
          </View>
        )}

        {/* Error message */}
        {error && (
          <View className="mb-3 rounded bg-status-error/20 px-2 py-1.5">
            <Text className="text-[12px] text-status-error">{error}</Text>
          </View>
        )}

        {/* Action button */}
        {showAction && (
          <TouchableOpacity
            onPress={handleRunTask}
            disabled={isRunning || !args.description}
            className={`flex-row items-center justify-center gap-2 rounded-lg px-4 py-2.5 ${
              isRunning ? "bg-accent-9/50" : "bg-accent-9"
            }`}
            activeOpacity={0.7}
          >
            {isRunning ? (
              <ActivityIndicator
                size={14}
                color={themeColors.accent.contrast}
              />
            ) : (
              <Play
                size={14}
                color={themeColors.accent.contrast}
                weight="fill"
              />
            )}
            <Text className="font-medium text-[13px] text-accent-contrast">
              {isRunning ? "Starting..." : "Open this task"}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
}

export function ToolMessage({
  toolName,
  rawToolName,
  kind,
  status,
  args,
  result,
  hasHumanMessageAfter,
  onOpenTask,
}: ToolMessageProps) {
  const themeColors = useThemeColors();
  const [isOpen, setIsOpen] = useState(false);

  const isLoading = status === "pending" || status === "running";
  const isFailed = status === "error";
  const displayTitle = formatToolTitle(toolName, args);
  const KindIcon = kind ? kindIcons[kind] : Wrench;
  const effectiveToolName = rawToolName ?? toolName;

  const isCreateTask =
    effectiveToolName.toLowerCase() === "create_task" || kind === "create_task";

  // File-editing tools get a proper diff view using the rawInput we already
  // receive on the wire. Detection is by shape, not tool name, so it works
  // regardless of how the agent labels the tool.
  const editArgs = asEditArgs(args);
  const multiEditArgs = !editArgs ? asMultiEditArgs(args) : null;
  const writeArgs = !editArgs && !multiEditArgs ? asWriteArgs(args) : null;
  const fileToolArgs = editArgs ?? multiEditArgs ?? writeArgs;

  // Unified-diff-in-result: when the agent runs commands like `git diff`
  // via the Bash tool, the result comes back as stdout containing a unified
  // diff string. Detect that and render it as a real diff view.
  const unifiedDiffText = !fileToolArgs ? extractDiffFromResult(result) : null;

  if (fileToolArgs && !isCreateTask) {
    const stats = countDiffLines(editArgs, multiEditArgs, writeArgs);
    const diffLanguage = languageFromPath(fileToolArgs.file_path);
    // Collapse diffs for failed edits (retries make them noise)
    const showDiff = !isFailed || isOpen;

    return (
      <View className="px-4 py-1">
        {/* Header row */}
        <Pressable
          onPress={() => isFailed && setIsOpen(!isOpen)}
          className="flex-row items-center gap-2"
          disabled={!isFailed}
        >
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.gray[9]} />
          ) : (
            <PencilSimple
              size={12}
              color={isFailed ? themeColors.status.error : themeColors.gray[9]}
            />
          )}
          <Text
            className={`font-mono text-[13px] ${isFailed ? "text-gray-9" : "text-gray-12"}`}
            numberOfLines={1}
          >
            {shortenPath(fileToolArgs.file_path)}
          </Text>
          {stats.added > 0 && !isFailed && (
            <Text className="font-mono text-[11px] text-status-success">
              +{stats.added}
            </Text>
          )}
          {stats.removed > 0 && !isFailed && (
            <Text className="font-mono text-[11px] text-status-error">
              -{stats.removed}
            </Text>
          )}
          {diffLanguage && !isFailed && (
            <Text className="font-mono text-[10px] text-gray-8">
              {diffLanguage}
            </Text>
          )}
          {isFailed && (
            <Text className="font-mono text-[12px] text-status-error">
              Failed
            </Text>
          )}
        </Pressable>

        {/* Diff content — collapsed when failed */}
        {showDiff && (
          <>
            {editArgs && (
              <DiffBlock
                oldText={editArgs.old_string}
                newText={editArgs.new_string}
                language={languageFromPath(fileToolArgs.file_path)}
              />
            )}
            {multiEditArgs?.edits.map((edit, i) => (
              <DiffBlock
                key={`${multiEditArgs.file_path}-${i}`}
                oldText={edit.old_string}
                newText={edit.new_string}
                language={languageFromPath(fileToolArgs.file_path)}
              />
            ))}
            {writeArgs && (
              <DiffBlock
                oldText=""
                newText={writeArgs.content}
                language={languageFromPath(fileToolArgs.file_path)}
              />
            )}
          </>
        )}
      </View>
    );
  }

  // Unified-diff-in-result renderer (e.g. `git diff` via Bash)
  if (unifiedDiffText && !isCreateTask) {
    return (
      <View className="px-4 py-1">
        <View className="flex-row items-center gap-2">
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.gray[9]} />
          ) : (
            <KindIcon size={12} color={themeColors.gray[9]} />
          )}
          <Text
            className="font-mono text-[13px] text-gray-12"
            numberOfLines={1}
          >
            {displayTitle}
          </Text>
          {isFailed && (
            <Text className="font-mono text-[13px] text-gray-9">(Failed)</Text>
          )}
        </View>
        <UnifiedDiffBlock diffText={unifiedDiffText} />
      </View>
    );
  }

  // For create_task, show rich preview instead of expandable
  if (isCreateTask && args) {
    return (
      <View className="px-4 py-1">
        <View className="mb-1 flex-row items-center gap-2">
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.gray[9]} />
          ) : (
            <ListChecks size={12} color={themeColors.accent[9]} />
          )}
          <Text className="font-mono text-[13px] text-gray-11">
            create_task
          </Text>
        </View>
        <CreateTaskPreview
          args={args as CreateTaskArgs}
          showAction={!hasHumanMessageAfter}
          onOpenTask={onOpenTask}
        />
      </View>
    );
  }

  const resolvedKind = kind ?? deriveToolKind(toolName);
  const isPending = status === "pending";
  const isRunning = status === "running";
  const isCompleted = status === "completed";
  const resultText = extractResultText(result);
  const isPostHogExec = isPostHogExecTool(effectiveToolName);
  const posthogExecDisplay = isPostHogExec ? getPostHogExecDisplay(args) : null;

  // MCP App tools render via the WebView host — skip PostHog exec (which has
  // its own renderer above) and only kick in once the tool finished or while
  // it's running so we don't show empty WebView shells for pending tools.
  const isMcpAppTool = !isPostHogExec && isMcpToolName(effectiveToolName);

  if (isMcpAppTool && !isPending) {
    return (
      <View className="px-4 py-1">
        <McpAppHost
          rawToolName={effectiveToolName}
          toolArgs={args}
          toolResult={result}
          status={status}
        />
      </View>
    );
  }

  if (isPostHogExec) {
    const label = posthogExecDisplay?.label ?? "exec";
    const inputPreview = posthogExecDisplay?.input;
    const fullInput =
      formatPosthogExecBody(posthogExecDisplay?.input) ??
      (typeof args?.command === "string" ? args.command : undefined);
    const outputText = resultText ? stripAnsi(resultText) : null;
    const hasOutput = !!outputText?.trim();
    const isExpandable = !!fullInput || hasOutput;
    // Surface output for failures too — otherwise a failed call shows "Failed"
    // with no reason, even though the error text lives in the result content.
    const showOutput = (isCompleted || isFailed) && hasOutput;

    return (
      <View className={`px-4 py-1 ${isRunning ? "bg-accent-3/30" : ""}`}>
        <Pressable
          onPress={() => isExpandable && setIsOpen(!isOpen)}
          className="flex-row items-center gap-2"
          disabled={!isExpandable}
        >
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.gray[9]} />
          ) : (
            <Wrench
              size={12}
              color={isFailed ? themeColors.status.error : themeColors.gray[9]}
            />
          )}
          <Text
            className="flex-1 font-mono text-[13px] text-gray-12"
            numberOfLines={1}
          >
            posthog - {label} (MCP)
          </Text>
          {isPending && (
            <Text className="font-mono text-[11px] text-gray-8">Queued</Text>
          )}
          {isFailed && (
            <Text className="font-mono text-[12px] text-status-error">
              Failed
            </Text>
          )}
        </Pressable>

        {inputPreview && !isPending && (
          <Text
            className="mt-0.5 ml-5 font-mono text-[11px] text-gray-9"
            numberOfLines={2}
            ellipsizeMode="tail"
          >
            {truncateText(inputPreview, POSTHOG_EXEC_INPUT_PREVIEW_MAX_LENGTH)}
          </Text>
        )}

        {isOpen && fullInput && (
          <View className="mt-1.5 ml-5 rounded border border-gray-6 bg-gray-2 px-2 py-1.5">
            <Text
              className="font-mono text-[11px] text-gray-11 leading-4"
              selectable
            >
              {fullInput}
            </Text>
          </View>
        )}

        {isOpen && showOutput && outputText && (
          <View className="mt-1.5 ml-5 rounded border border-gray-6 bg-gray-2 px-2 py-1.5">
            <Text
              className="font-mono text-[11px] text-gray-11 leading-4"
              numberOfLines={30}
              selectable
            >
              {outputText}
            </Text>
          </View>
        )}
      </View>
    );
  }

  // Execute/Bash: show description + command subtitle + expandable output
  if (resolvedKind === "execute") {
    const command = typeof args?.command === "string" ? args.command : null;
    const description =
      typeof args?.description === "string" ? args.description : null;
    const outputText = resultText ? stripAnsi(resultText) : null;
    const hasOutput = outputText && outputText.trim().length > 0;

    return (
      <View className={`px-4 py-1 ${isRunning ? "bg-accent-3/30" : ""}`}>
        {/* Header */}
        <Pressable
          onPress={() => hasOutput && setIsOpen(!isOpen)}
          className="flex-row items-center gap-2"
          disabled={!hasOutput}
        >
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.gray[9]} />
          ) : (
            <Terminal
              size={12}
              color={isFailed ? themeColors.status.error : themeColors.gray[9]}
            />
          )}
          <Text
            className="font-mono text-[13px] text-gray-12"
            numberOfLines={1}
          >
            {description ?? displayTitle}
          </Text>
          {isFailed && (
            <Text className="font-mono text-[12px] text-status-error">
              Failed
            </Text>
          )}
        </Pressable>

        {/* Command as subtitle line */}
        {command && (
          <Text
            className="mt-0.5 ml-5 font-mono text-[11px] text-gray-9"
            numberOfLines={2}
            ellipsizeMode="tail"
          >
            $ {command}
          </Text>
        )}

        {/* Output */}
        {isOpen && hasOutput && (
          <View className="mt-1.5 ml-5 rounded border border-gray-6 bg-gray-2 px-2 py-1.5">
            <Text
              className="font-mono text-[11px] text-gray-11 leading-4"
              numberOfLines={30}
              selectable
            >
              {outputText}
            </Text>
          </View>
        )}
      </View>
    );
  }

  // Read: show file path, line range, and expandable content preview
  if (resolvedKind === "read") {
    // Try args first, then extract a path from the tool title (e.g.
    // "Read `src/foo.ts`" or "Read 200 lines in `bar.ts`").
    const filePath =
      typeof args?.file_path === "string"
        ? args.file_path
        : typeof args?.target_file === "string"
          ? args.target_file
          : extractPathFromTitle(toolName);
    const hasContent = resultText && resultText.trim().length > 0;
    const lineCount = hasContent ? resultText.split("\n").length : null;
    const offset = typeof args?.offset === "number" ? args.offset : null;
    const limit = typeof args?.limit === "number" ? args.limit : null;
    const lineRange = offset
      ? `lines ${offset}–${offset + (limit ?? lineCount ?? 0)}`
      : lineCount
        ? `${lineCount} lines`
        : null;

    return (
      <View className={`px-4 py-1 ${isRunning ? "bg-accent-3/30" : ""}`}>
        <Pressable
          onPress={() => hasContent && setIsOpen(!isOpen)}
          className="flex-row items-center gap-2"
          disabled={!hasContent}
        >
          {isLoading ? (
            <ActivityIndicator size={12} color={themeColors.gray[9]} />
          ) : (
            <FileText size={12} color={themeColors.gray[9]} />
          )}
          <Text
            className="font-mono text-[13px] text-gray-11"
            numberOfLines={1}
          >
            Read
          </Text>
          {filePath ? (
            <Text
              className="flex-1 font-mono text-[13px] text-gray-12"
              numberOfLines={1}
              ellipsizeMode="middle"
            >
              {shortenPath(filePath, 36)}
            </Text>
          ) : null}
          {lineRange && isCompleted && (
            <Text className="font-mono text-[11px] text-gray-9">
              {lineRange}
            </Text>
          )}
          {isFailed && (
            <Text className="font-mono text-[12px] text-status-error">
              Failed
            </Text>
          )}
        </Pressable>

        {/* Content preview */}
        {isOpen && hasContent && (
          <View className="mt-1.5 ml-5 rounded border border-gray-6 bg-gray-2 px-2 py-1.5">
            <Text
              className="font-mono text-[11px] text-gray-11 leading-4"
              numberOfLines={20}
              selectable
            >
              {resultText}
            </Text>
          </View>
        )}
      </View>
    );
  }

  // Default: all other tools (search, think, fetch, etc.)
  const subtitle = getToolSubtitle(toolName, args);

  return (
    <View
      className={`px-4 py-0.5 ${
        isRunning ? "bg-accent-3/30" : isPending ? "opacity-50" : ""
      }`}
    >
      <View className="flex-row items-center gap-2">
        {/* Status indicator */}
        {isLoading ? (
          <ActivityIndicator size={12} color={themeColors.gray[9]} />
        ) : (
          <KindIcon
            size={12}
            color={isFailed ? themeColors.status.error : themeColors.gray[9]}
          />
        )}

        {/* Tool name */}
        <Text className="font-mono text-[13px] text-gray-12" numberOfLines={1}>
          {displayTitle}
        </Text>

        {/* Queued label */}
        {isPending && (
          <Text className="font-mono text-[11px] text-gray-8">Queued</Text>
        )}

        {/* Failed indicator */}
        {isFailed && (
          <Text className="font-mono text-[12px] text-status-error">
            Failed
          </Text>
        )}
      </View>

      {/* Contextual subtitle */}
      {subtitle && !isPending && (
        <Text
          className="mt-0.5 ml-5 font-mono text-[11px] text-gray-9"
          numberOfLines={1}
          ellipsizeMode="middle"
        >
          {subtitle}
        </Text>
      )}
    </View>
  );
}
