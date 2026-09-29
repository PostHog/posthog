import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Glass } from "@/components/Glass";
import { Markdown } from "@/components/Markdown";
import type { TaskSession } from "@/lib/session";
import { colors, fonts, radius } from "@/lib/theme";
import type { Block, PermissionRequest, ToolStatus } from "@/lib/transcript";

interface TranscriptProps {
  session: TaskSession;
  onPermission: (toolCallId: string, optionId: string) => void;
  // Fires with each user bubble's y offset inside the transcript, for scrolling.
  onUserLayout?: (blockId: string, y: number) => void;
}

type ToolBlock = Block & { kind: "tool" };
type ThoughtBlock = Block & { kind: "thought" };

interface Activity {
  kind: "activity";
  id: string;
  items: Array<ToolBlock | ThoughtBlock>;
  children: Map<string, ToolBlock[]>;
  toolCount: number;
  start: number;
  end: number;
}

type Row = { kind: "block"; block: Block } | Activity;

// Consecutive tool calls and thoughts collapse into one activity row, so the
// transcript reads as messages with a "Working" line between them.
function arrange(blocks: Block[]): Row[] {
  const children = new Map<string, ToolBlock[]>();
  for (const block of blocks) {
    if (block.kind === "tool" && block.parentId) {
      const list = children.get(block.parentId) ?? [];
      list.push(block);
      children.set(block.parentId, list);
    }
  }
  const rows: Row[] = [];
  let open: Activity | null = null;
  for (const block of blocks) {
    if (block.kind === "tool" && block.parentId) continue;
    if (block.kind === "tool" || block.kind === "thought") {
      if (!open) {
        open = {
          kind: "activity",
          id: `activity-${block.id}`,
          items: [],
          children,
          toolCount: 0,
          start: block.at,
          end: block.at,
        };
        rows.push(open);
      }
      open.items.push(block);
      const latest = block.kind === "tool" ? block.updatedAt : block.at;
      open.end = Math.max(open.end, latest);
      if (block.kind === "tool") {
        open.toolCount += 1 + (children.get(block.id)?.length ?? 0);
        for (const child of children.get(block.id) ?? []) {
          open.end = Math.max(open.end, child.updatedAt);
        }
      }
      continue;
    }
    open = null;
    rows.push({ kind: "block", block });
  }
  return rows;
}

export function Transcript({
  session,
  onPermission,
  onUserLayout,
}: TranscriptProps) {
  const rows = useMemo(() => arrange(session.blocks), [session.blocks]);
  const lastRow = rows[rows.length - 1];
  const orphanPermissions = Object.values(session.permissions).filter(
    (request) =>
      !session.blocks.some((block) => block.id === request.toolCallId),
  );
  return (
    <View style={styles.list}>
      {rows.map((row) =>
        row.kind === "activity" ? (
          <ActivityRow
            key={row.id}
            activity={row}
            active={session.turnActive && row === lastRow}
            permissions={session.permissions}
            onPermission={onPermission}
          />
        ) : (
          <BlockView
            key={row.block.id}
            block={row.block}
            onUserLayout={onUserLayout}
          />
        ),
      )}
      {orphanPermissions.map((request) => (
        <PermissionCard
          key={request.requestId}
          request={request}
          onPermission={onPermission}
        />
      ))}
      {session.turnActive && lastRow?.kind !== "activity" ? (
        <StatusLine label="Working" active />
      ) : null}
    </View>
  );
}

function BlockView({
  block,
  onUserLayout,
}: {
  block: Block;
  onUserLayout?: TranscriptProps["onUserLayout"];
}) {
  switch (block.kind) {
    case "user":
      return (
        <View
          style={styles.userRow}
          onLayout={(event) =>
            onUserLayout?.(block.id, event.nativeEvent.layout.y)
          }
        >
          <View style={styles.userBubble}>
            <Text style={styles.userText} selectable>
              {block.text}
            </Text>
          </View>
        </View>
      );
    case "agent":
      return (
        <View style={styles.agentRow}>
          <Markdown text={block.text} />
        </View>
      );
    case "plan":
      return (
        <View style={styles.plan}>
          <Text style={styles.planTitle}>Plan</Text>
          {block.entries.map((entry, index) => (
            <View key={`${index}-${entry.content}`} style={styles.planRow}>
              <Text style={styles.planMark}>
                {entry.status === "completed"
                  ? "✓"
                  : entry.status === "in_progress"
                    ? "›"
                    : "○"}
              </Text>
              <Text
                style={[
                  styles.planText,
                  entry.status === "completed" && { color: colors.inkMute },
                ]}
              >
                {entry.content}
              </Text>
            </View>
          ))}
        </View>
      );
    default:
      return null;
  }
}

function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [enabled]);
  return now;
}

function StatusLine({
  label,
  active,
  detail,
  open,
  onPress,
}: {
  label: string;
  active: boolean;
  detail?: string;
  open?: boolean;
  onPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => [styles.status, pressed && { opacity: 0.6 }]}
    >
      {onPress ? (
        <Text style={[styles.chevron, open && styles.chevronOpen]}>›</Text>
      ) : null}
      <Text style={styles.statusLabel}>{label}</Text>
      {active ? (
        <ActivityIndicator size="small" color={colors.inkMute} />
      ) : null}
      {detail ? <Text style={styles.statusDetail}>{detail}</Text> : null}
    </Pressable>
  );
}

function ActivityRow({
  activity,
  active,
  permissions,
  onPermission,
}: {
  activity: Activity;
  active: boolean;
  permissions: TaskSession["permissions"];
  onPermission: TranscriptProps["onPermission"];
}) {
  const [open, setOpen] = useState(false);
  const now = useNow(active);
  const elapsed = formatDuration(
    (active ? now : activity.end) - activity.start,
  );
  const calls = `${activity.toolCount} tool call${
    activity.toolCount === 1 ? "" : "s"
  }`;
  const pending = activity.items
    .filter((item): item is ToolBlock => item.kind === "tool")
    .flatMap((tool) => [tool, ...(activity.children.get(tool.id) ?? [])])
    .map((tool) => permissions[tool.id])
    .filter((request): request is PermissionRequest => !!request);
  const latestThought = active
    ? [...activity.items].reverse().find((item) => item.kind === "thought")
    : undefined;

  return (
    <View style={styles.activity}>
      <StatusLine
        label={active ? "Working" : "Worked"}
        active={active}
        detail={`· ${elapsed}${activity.toolCount > 0 ? ` · ${calls}` : ""}`}
        open={open}
        onPress={() => setOpen((value) => !value)}
      />
      {!open && latestThought ? (
        <Text style={styles.thinkingPeek} numberOfLines={1}>
          {latestThought.text.trim()}
        </Text>
      ) : null}
      {open ? (
        <View style={styles.activityBody}>
          {activity.items.map((item) =>
            item.kind === "thought" ? (
              <Text key={item.id} style={styles.thoughtText} selectable>
                {item.text.trim()}
              </Text>
            ) : (
              <View key={item.id}>
                <ToolRow block={item} />
                {(activity.children.get(item.id) ?? []).map((child) => (
                  <ToolRow key={child.id} block={child} nested />
                ))}
              </View>
            ),
          )}
        </View>
      ) : null}
      {pending.map((request) => (
        <PermissionCard
          key={request.requestId}
          request={request}
          onPermission={onPermission}
        />
      ))}
    </View>
  );
}

function statusColor(status: ToolStatus): string {
  switch (status) {
    case "completed":
      return colors.ok;
    case "failed":
      return colors.danger;
    case "running":
      return colors.accent;
    default:
      return colors.inkMute;
  }
}

function summarizeInput(input?: Record<string, unknown>): string {
  if (!input) return "";
  const preferred = [
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "description",
    "prompt",
  ];
  for (const key of preferred) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  const first = Object.values(input).find((value) => typeof value === "string");
  return typeof first === "string" ? first : "";
}

function pretty(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function ToolRow({ block, nested }: { block: ToolBlock; nested?: boolean }) {
  const [open, setOpen] = useState(false);
  const summary = summarizeInput(block.input);
  return (
    <Pressable
      onPress={() => setOpen((value) => !value)}
      style={[styles.tool, nested && styles.toolNested]}
    >
      <View style={styles.toolHeader}>
        {block.status === "running" ? (
          <ActivityIndicator size="small" color={colors.accent} />
        ) : (
          <View
            style={[
              styles.toolDot,
              { backgroundColor: statusColor(block.status) },
            ]}
          />
        )}
        <Text style={styles.toolTitle} numberOfLines={1}>
          {block.toolName ?? block.title}
        </Text>
        {summary ? (
          <Text style={styles.toolSummary} numberOfLines={1}>
            {summary}
          </Text>
        ) : null}
      </View>
      {open ? (
        <View style={styles.toolDetail}>
          {block.input ? (
            <>
              <Text style={styles.detailLabel}>Input</Text>
              <Text style={styles.detailText} selectable>
                {pretty(block.input)}
              </Text>
            </>
          ) : null}
          {block.output !== undefined ? (
            <>
              <Text style={styles.detailLabel}>Output</Text>
              <Text style={styles.detailText} selectable numberOfLines={60}>
                {pretty(block.output)}
              </Text>
            </>
          ) : null}
        </View>
      ) : null}
    </Pressable>
  );
}

function PermissionCard({
  request,
  onPermission,
}: {
  request: PermissionRequest;
  onPermission: TranscriptProps["onPermission"];
}) {
  const summary = summarizeInput(request.input);
  const answered = !!request.chosenOptionId;
  return (
    <Glass style={styles.permission} tint="rgba(217,117,91,0.08)">
      <Text style={styles.permissionTitle}>{request.title}</Text>
      {summary ? (
        <Text style={styles.detailText} numberOfLines={4}>
          {summary}
        </Text>
      ) : null}
      <View style={styles.optionRow}>
        {request.options.map((option) => {
          const primary = option.kind.startsWith("allow");
          const chosen = request.chosenOptionId === option.optionId;
          return (
            <Pressable
              key={option.optionId}
              disabled={answered}
              onPress={() => onPermission(request.toolCallId, option.optionId)}
              style={({ pressed }) => [
                styles.option,
                primary ? styles.optionPrimary : styles.optionSecondary,
                (pressed || (answered && !chosen)) && { opacity: 0.5 },
              ]}
            >
              <Text
                style={
                  primary
                    ? styles.optionPrimaryText
                    : styles.optionSecondaryText
                }
              >
                {option.name}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </Glass>
  );
}

const styles = StyleSheet.create({
  list: { gap: 16, paddingHorizontal: 18 },
  userRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    marginTop: 12,
    marginBottom: 6,
  },
  userBubble: {
    maxWidth: "84%",
    backgroundColor: colors.dark,
    borderRadius: radius.bubble,
    borderBottomRightRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  userText: { color: colors.darkText, fontSize: 16, lineHeight: 22 },
  agentRow: { paddingRight: 8 },
  status: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 4,
  },
  chevron: {
    fontSize: 20,
    lineHeight: 22,
    color: colors.inkMute,
    width: 12,
    textAlign: "center",
  },
  chevronOpen: { transform: [{ rotate: "90deg" }] },
  statusLabel: { fontSize: 16, color: colors.ink },
  statusDetail: { fontSize: 15, color: colors.inkMute },
  activity: { gap: 6 },
  thinkingPeek: {
    color: colors.inkMute,
    fontSize: 14,
    lineHeight: 20,
    paddingLeft: 20,
    fontStyle: "italic",
  },
  activityBody: { gap: 6, paddingLeft: 8 },
  thoughtText: {
    color: colors.inkMute,
    fontSize: 14,
    lineHeight: 20,
    fontStyle: "italic",
    paddingVertical: 4,
  },
  tool: { paddingVertical: 6 },
  toolNested: { paddingLeft: 18 },
  toolHeader: { flexDirection: "row", alignItems: "center", gap: 8 },
  toolDot: { width: 7, height: 7, borderRadius: 4 },
  toolTitle: { fontFamily: fonts.monoMedium, fontSize: 12, color: colors.ink },
  toolSummary: {
    flex: 1,
    fontFamily: fonts.mono,
    fontSize: 12,
    color: colors.inkSoft,
  },
  toolDetail: { marginTop: 8, gap: 4, paddingLeft: 15 },
  detailLabel: {
    fontFamily: fonts.monoMedium,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.inkMute,
  },
  detailText: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 17,
    color: colors.inkSoft,
  },
  permission: {
    borderRadius: radius.card,
    padding: 14,
    gap: 8,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "rgba(217,117,91,0.35)",
  },
  permissionTitle: { fontSize: 15, fontWeight: "600", color: colors.ink },
  optionRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4 },
  option: {
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: radius.pill,
  },
  optionPrimary: { backgroundColor: colors.dark },
  optionSecondary: { backgroundColor: "rgba(28,27,24,0.08)" },
  optionPrimaryText: {
    color: colors.darkText,
    fontWeight: "600",
    fontSize: 14,
  },
  optionSecondaryText: { color: colors.ink, fontWeight: "500", fontSize: 14 },
  plan: { gap: 8, paddingVertical: 4 },
  planTitle: { fontSize: 15, fontWeight: "600", color: colors.ink },
  planRow: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  planMark: {
    fontFamily: fonts.mono,
    color: colors.inkMute,
    width: 14,
    lineHeight: 20,
  },
  planText: { flex: 1, fontSize: 14, lineHeight: 20, color: colors.ink },
});
