import { getObjectKind } from "@posthog/core/inbox/objectTags";
import { isSafeExternalUrl } from "@posthog/shared";
import { type ReactElement, useState } from "react";
import { Linking, Pressable, StyleSheet, Text } from "react-native";
import { useAuth } from "@/lib/auth";
import { type ObjectCardSpec, objectWebUrl } from "@/lib/objectTags";
import { useInsightSummary } from "@/lib/queries";
import { colors, fonts } from "@/lib/theme";

const COLLAPSED_LINES = 3;

export function useObjectUrl(kind: string, id: string): string | null {
  const session = useAuth((s) => s.session);
  return session
    ? objectWebUrl(session.host, session.projectId, kind, id)
    : null;
}

export function openObjectUrl(url: string | null): void {
  if (url && isSafeExternalUrl(url)) Linking.openURL(url).catch(() => {});
}

function meta(kind: string): string {
  const { kindLabel, source } = getObjectKind(kind);
  return `${kindLabel} · ${source}`;
}

function InsightCard({
  shortId,
  title,
}: {
  shortId: string;
  title?: string;
}): ReactElement {
  const insight = useInsightSummary(shortId);
  const url = useObjectUrl("insight", shortId);
  const name = title ?? insight.data?.name;
  const placeholder = insight.isLoading
    ? "Loading"
    : insight.isError || insight.data === null
      ? "Couldn't load this insight."
      : "Untitled insight";
  return (
    <Pressable
      onPress={() => openObjectUrl(url)}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <Text style={styles.meta}>{meta("insight")}</Text>
      {name ? (
        <Text style={styles.title} numberOfLines={2}>
          {name}
        </Text>
      ) : (
        <Text style={styles.muted}>{placeholder}</Text>
      )}
      {insight.data?.description ? (
        <Text style={styles.description} numberOfLines={3}>
          {insight.data.description}
        </Text>
      ) : null}
    </Pressable>
  );
}

function QueryCard({
  query,
  title,
}: {
  query: string;
  title?: string;
}): ReactElement {
  const url = useObjectUrl("hogql", query);
  const [expanded, setExpanded] = useState(false);
  const long = query.split("\n").length > COLLAPSED_LINES;
  return (
    <Pressable
      onPress={() => openObjectUrl(url)}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <Text style={styles.meta}>{meta("hogql")}</Text>
      <Text style={styles.title} numberOfLines={2}>
        {title ?? "SQL query"}
      </Text>
      <Text
        style={styles.query}
        numberOfLines={expanded ? undefined : COLLAPSED_LINES}
      >
        {query}
      </Text>
      {long ? (
        <Pressable hitSlop={8} onPress={() => setExpanded(!expanded)}>
          <Text style={styles.toggle}>
            {expanded ? "Show less" : "Show all"}
          </Text>
        </Pressable>
      ) : null}
    </Pressable>
  );
}

export function ObjectCard({ spec }: { spec: ObjectCardSpec }): ReactElement {
  return spec.mode === "insight" ? (
    <InsightCard shortId={spec.shortId} title={spec.title} />
  ) : (
    <QueryCard query={spec.query} title={spec.title} />
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 12,
    gap: 6,
  },
  pressed: { opacity: 0.5 },
  meta: { fontFamily: fonts.sansMedium, fontSize: 12, color: colors.inkMute },
  title: {
    fontFamily: fonts.sansSemi,
    fontSize: 15,
    lineHeight: 20,
    color: colors.ink,
  },
  description: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: colors.inkSoft,
  },
  muted: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkMute },
  query: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 17,
    color: colors.inkSoft,
    backgroundColor: colors.code,
    borderRadius: 8,
    padding: 8,
    overflow: "hidden",
  },
  toggle: { fontFamily: fonts.sansMedium, fontSize: 13, color: colors.accent },
});
