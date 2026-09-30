import type { Schemas } from "@posthog/api-client";
import { colors as brand } from "@posthog/brand/colors";
import { isSafeExternalUrl } from "@posthog/shared";
import { FlashList } from "@shopify/flash-list";
import { useLocalSearchParams } from "expo-router";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  type ColorValue,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SheetHeader } from "@/components/SheetHeader";
import { sheetStyles } from "@/components/SheetRow";
import { useTaskReview } from "@/lib/queries";
import {
  fileStatusLabel,
  type PatchLineKind,
  parsePatch,
  prFilesUrl,
  reviewErrorMessage,
  splitPath,
} from "@/lib/review";
import { colors, fonts, radius } from "@/lib/theme";

type ReviewFile = Schemas.TaskReviewFile;

interface Tone {
  bg: ColorValue;
  fg: ColorValue;
}

const GREEN: Tone = { bg: "rgba(71,200,97,0.16)", fg: brand.green.darker };
const RED: Tone = { bg: "rgba(255,71,77,0.16)", fg: colors.danger };
const ORANGE: Tone = { bg: "rgba(255,92,28,0.16)", fg: colors.accent };
const PURPLE: Tone = { bg: "rgba(167,55,210,0.14)", fg: brand.purple.core };
const MUTED: Tone = { bg: colors.fill, fg: colors.inkSoft };

const STATE: Record<string, { label: string; tone: Tone }> = {
  open: { label: "Open", tone: GREEN },
  merged: { label: "Merged", tone: PURPLE },
  closed: { label: "Closed", tone: RED },
  draft: { label: "Draft", tone: MUTED },
};

const CI: Record<string, { label: string; tone: Tone }> = {
  passing: { label: "Checks passing", tone: GREEN },
  failing: { label: "Checks failing", tone: RED },
  pending: { label: "Checks running", tone: ORANGE },
  none: { label: "No checks", tone: MUTED },
};

const LINE: Record<PatchLineKind, { bg?: ColorValue; fg: ColorValue }> = {
  add: { bg: "rgba(71,200,97,0.14)", fg: colors.ink },
  del: { bg: "rgba(255,71,77,0.12)", fg: colors.ink },
  hunk: { bg: "rgba(20,144,232,0.10)", fg: colors.inkMute },
  meta: { fg: colors.inkMute },
  context: { fg: colors.inkSoft },
};

function openUrl(url: string): void {
  if (isSafeExternalUrl(url)) Linking.openURL(url).catch(() => {});
}

export default function ReviewSheet() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const review = useTaskReview(id);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const pr = review.data?.pages[0];
  const files = useMemo(
    () => review.data?.pages.flatMap((page) => page.files) ?? [],
    [review.data],
  );

  const toggle = (filename: string): void => {
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(filename)) next.add(filename);
      return next;
    });
  };

  return (
    <FlashList
      style={sheetStyles.root}
      data={files}
      keyExtractor={(file) => file.filename}
      extraData={expanded}
      renderItem={({ item, index }) => (
        <FileRow
          file={item}
          first={index === 0}
          last={index === files.length - 1}
          expanded={expanded.has(item.filename)}
          onToggle={() => toggle(item.filename)}
          filesUrl={pr ? prFilesUrl(pr.url) : ""}
        />
      )}
      contentContainerStyle={styles.content}
      ListHeaderComponent={
        <View style={styles.header}>
          <SheetHeader title="Pull request" />
          {pr ? <Summary pr={pr} /> : null}
        </View>
      }
      ListEmptyComponent={
        review.isLoading ? (
          <ActivityIndicator color={colors.inkSoft} style={styles.spinner} />
        ) : (
          <Text style={sheetStyles.footnote}>
            {review.isError
              ? reviewErrorMessage(review.error)
              : "No changed files."}
          </Text>
        )
      }
      ListFooterComponent={
        review.isFetchingNextPage ? (
          <ActivityIndicator color={colors.inkSoft} style={styles.spinner} />
        ) : review.isFetchNextPageError ? (
          <Text style={[sheetStyles.footnote, styles.footer]}>
            Could not load more files.
          </Text>
        ) : null
      }
      onEndReached={() => {
        if (review.hasNextPage && !review.isFetching) {
          void review.fetchNextPage();
        }
      }}
      onEndReachedThreshold={0.5}
    />
  );
}

function Chip({ label, tone }: { label: string; tone: Tone }) {
  return (
    <View style={[styles.chip, { backgroundColor: tone.bg }]}>
      <Text style={[styles.chipText, { color: tone.fg }]}>{label}</Text>
    </View>
  );
}

function Summary({ pr }: { pr: Schemas.TaskReview }) {
  const state = STATE[pr.state];
  const ci = CI[pr.ci_status] ?? CI.none;
  return (
    <View style={styles.summary}>
      <Text style={styles.title}>{pr.title}</Text>
      <View style={styles.chips}>
        {state ? <Chip label={state.label} tone={state.tone} /> : null}
        <Chip label={ci.label} tone={ci.tone} />
      </View>
      <Pressable
        onPress={() => openUrl(pr.url)}
        style={({ pressed }) => [styles.button, pressed && { opacity: 0.7 }]}
      >
        <Text style={styles.buttonText}>Open on GitHub</Text>
      </Pressable>
      <Text style={[sheetStyles.sectionTitle, styles.filesTitle]}>
        Changed files
      </Text>
    </View>
  );
}

function FileRow({
  file,
  first,
  last,
  expanded,
  onToggle,
  filesUrl,
}: {
  file: ReviewFile;
  first: boolean;
  last: boolean;
  expanded: boolean;
  onToggle: () => void;
  filesUrl: string;
}) {
  const { dir, base } = splitPath(file.filename);
  return (
    <View
      style={[
        styles.file,
        first && styles.fileFirst,
        last && styles.fileLast,
        !first && styles.fileDivider,
      ]}
    >
      <Pressable
        onPress={onToggle}
        style={({ pressed }) => [styles.fileRow, pressed && { opacity: 0.5 }]}
      >
        <View style={styles.fileText}>
          <Text style={styles.path} numberOfLines={2}>
            {dir}
            <Text style={styles.base}>{base}</Text>
          </Text>
          <Text style={styles.status}>{fileStatusLabel(file.status)}</Text>
        </View>
        <Text style={styles.counts}>
          <Text style={styles.added}>+{file.additions}</Text>{" "}
          <Text style={styles.deleted}>−{file.deletions}</Text>
        </Text>
        <Text style={[styles.chevron, expanded && styles.chevronOpen]}>›</Text>
      </Pressable>
      {expanded ? <Patch file={file} filesUrl={filesUrl} /> : null}
    </View>
  );
}

function Patch({ file, filesUrl }: { file: ReviewFile; filesUrl: string }) {
  const lines = useMemo(() => parsePatch(file.patch), [file.patch]);
  return (
    <View style={styles.patchWrap}>
      {lines.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.patch}
          contentContainerStyle={styles.patchContent}
        >
          <View style={styles.patchLines}>
            {lines.map((line, index) => (
              <Text
                key={String(index)}
                style={[
                  styles.line,
                  { color: LINE[line.kind].fg },
                  LINE[line.kind].bg != null && {
                    backgroundColor: LINE[line.kind].bg,
                  },
                ]}
              >
                {line.text || " "}
              </Text>
            ))}
          </View>
        </ScrollView>
      ) : null}
      {file.truncated || lines.length === 0 ? (
        <Pressable
          onPress={() => openUrl(filesUrl)}
          style={({ pressed }) => [
            styles.truncated,
            pressed && { opacity: 0.5 },
          ]}
        >
          <Text style={styles.truncatedText}>
            {`${lines.length > 0 ? "Diff truncated" : "No diff to show"} · View on GitHub`}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 18, paddingTop: 22, paddingBottom: 40 },
  header: { gap: 14, marginBottom: 8 },
  spinner: { marginTop: 24 },
  footer: { marginTop: 12 },
  summary: { gap: 12 },
  title: {
    fontFamily: fonts.sansBold,
    fontSize: 22,
    lineHeight: 28,
    color: colors.ink,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  chipText: { fontFamily: fonts.sansBold, fontSize: 12 },
  button: {
    alignItems: "center",
    paddingVertical: 12,
    borderRadius: radius.pill,
    backgroundColor: colors.fill,
  },
  buttonText: { fontFamily: fonts.sansSemi, fontSize: 15, color: colors.ink },
  filesTitle: { marginTop: 10 },
  file: { backgroundColor: colors.surface, paddingHorizontal: 16 },
  fileFirst: {
    borderTopLeftRadius: radius.card,
    borderTopRightRadius: radius.card,
  },
  fileLast: {
    borderBottomLeftRadius: radius.card,
    borderBottomRightRadius: radius.card,
  },
  fileDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  fileRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
  },
  fileText: { flex: 1, gap: 2 },
  path: { fontFamily: fonts.sans, fontSize: 15, color: colors.inkMute },
  base: { fontFamily: fonts.sansSemi, color: colors.ink },
  status: { fontFamily: fonts.sans, fontSize: 13, color: colors.inkMute },
  counts: { fontFamily: fonts.mono, fontSize: 12 },
  added: { color: colors.ok },
  deleted: { color: colors.danger },
  chevron: { fontSize: 20, lineHeight: 22, color: colors.inkMute },
  chevronOpen: { transform: [{ rotate: "90deg" }] },
  patchWrap: { gap: 8, paddingBottom: 12 },
  patch: { backgroundColor: colors.code, borderRadius: 12 },
  patchContent: { flexGrow: 1, paddingVertical: 8 },
  patchLines: { flexGrow: 1 },
  line: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 18,
    paddingHorizontal: 10,
  },
  truncated: { paddingVertical: 4 },
  truncatedText: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.accent,
  },
});
