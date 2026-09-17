import {
  deriveHeadline,
  formatSignalReportSummaryMarkdown,
  parseConventionalCommitTitle,
  splitReportSummary,
} from "@posthog/core/inbox/reportPresentation";
import { formatRelativeAge } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportPriority,
  SuggestedReviewersArtefact,
} from "@posthog/shared/domain-types";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Markdown } from "@/components/Markdown";
import { useReportArtefacts, useReportSignals } from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

const PRIORITY: Record<SignalReportPriority, { bg: string; fg: string }> = {
  P0: { bg: "rgba(255,71,77,0.16)", fg: colors.danger },
  P1: { bg: "rgba(255,92,28,0.16)", fg: colors.accent },
  P2: { bg: "rgba(20,144,232,0.14)", fg: "#106FB2" },
  P3: { bg: "rgba(21,21,21,0.06)", fg: colors.inkSoft },
  P4: { bg: "rgba(21,21,21,0.06)", fg: colors.inkSoft },
};

function sourceLabel(products: string[] | undefined): string {
  const first = products?.[0];
  if (!first) return "Signal";
  return first
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function parsedTitle(report: SignalReport): {
  tag: string | null;
  text: string;
} {
  const raw =
    report.title ?? deriveHeadline(report.summary) ?? "Untitled report";
  const parsed = parseConventionalCommitTitle(raw);
  if (!parsed) return { tag: null, text: raw };
  const scope = parsed.scope ? `(${parsed.scope})` : "";
  return { tag: `${parsed.type}${scope}`, text: parsed.description };
}

export function PriorityChip({ priority }: { priority: SignalReportPriority }) {
  const tone = PRIORITY[priority];
  return (
    <View style={[styles.priority, { backgroundColor: tone.bg }]}>
      <Text style={[styles.priorityText, { color: tone.fg }]}>{priority}</Text>
    </View>
  );
}

// The face of a triage card: source, priority, title, lede and the meta line.
// The top card also previews the first pieces of evidence.
export function ReportSummary({
  report,
  withEvidence,
  hideLede,
}: {
  report: SignalReport;
  withEvidence?: boolean;
  hideLede?: boolean;
}) {
  const title = parsedTitle(report);
  const lede = hideLede ? null : deriveHeadline(report.summary);
  return (
    <View style={styles.summary}>
      <Text style={styles.source}>{sourceLabel(report.source_products)}</Text>
      <View style={styles.titleRow}>
        {report.priority ? <PriorityChip priority={report.priority} /> : null}
        {title.tag ? <Text style={styles.tag}>{title.tag}</Text> : null}
      </View>
      <Text style={styles.title}>{title.text}</Text>
      {lede && lede !== title.text ? (
        <Text style={styles.lede} numberOfLines={5}>
          {lede}
        </Text>
      ) : null}
      <Text style={styles.meta}>
        {report.signal_count} signal{report.signal_count === 1 ? "" : "s"} ·
        First seen {formatRelativeAge(report.created_at)} · Updated{" "}
        {formatRelativeAge(report.updated_at)}
      </Text>
      {withEvidence ? <EvidencePreview reportId={report.id} /> : null}
    </View>
  );
}

function EvidencePreview({ reportId }: { reportId: string }) {
  const signals = useReportSignals(reportId);
  const evidence = (signals.data?.signals ?? []).slice(0, 2);
  if (evidence.length === 0) return null;
  return (
    <View style={styles.preview}>
      <Text style={styles.previewTitle}>Evidence</Text>
      {evidence.map((signal) => (
        <View key={signal.signal_id} style={styles.evidence}>
          <Text style={styles.evidenceMeta}>
            {sourceLabel([signal.source_product])} ·{" "}
            {formatRelativeAge(signal.timestamp)}
          </Text>
          <Text style={styles.evidenceBody} numberOfLines={4}>
            {signal.content.trim()}
          </Text>
        </View>
      ))}
    </View>
  );
}

// The expanded card: full summary sections, evidence and reviewers.
export function ReportDetail({ report }: { report: SignalReport }) {
  const signals = useReportSignals(report.id);
  const artefacts = useReportArtefacts(report.id);
  const summary = splitReportSummary(
    report.summary ? formatSignalReportSummaryMarkdown(report.summary) : "",
  );
  const reviewers = artefacts.data?.results.find(
    (artefact): artefact is SuggestedReviewersArtefact =>
      artefact.type === "suggested_reviewers",
  );
  const evidence = signals.data?.signals ?? [];

  return (
    <ScrollView
      style={styles.detail}
      contentContainerStyle={styles.detailContent}
      showsVerticalScrollIndicator={false}
    >
      <ReportSummary report={report} hideLede />
      {report.already_addressed ? (
        <View style={styles.notice}>
          <Text style={styles.noticeTitle}>Likely already fixed</Text>
          <Text style={styles.noticeBody}>
            The evidence suggests this was addressed. Skim the summary and
            dismiss it if you agree.
          </Text>
        </View>
      ) : null}
      {summary.lede ? <Markdown text={summary.lede} /> : null}
      {summary.sections.map((section) => (
        <View key={section.title} style={styles.section}>
          <Text style={styles.sectionTitle}>{section.title}</Text>
          <Markdown text={section.body} />
        </View>
      ))}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>
          Evidence{evidence.length ? ` · ${evidence.length}` : ""}
        </Text>
        {signals.isLoading ? <Text style={styles.muted}>Loading</Text> : null}
        {evidence.map((signal) => (
          <View key={signal.signal_id} style={styles.evidence}>
            <Text style={styles.evidenceMeta}>
              {sourceLabel([signal.source_product])} ·{" "}
              {formatRelativeAge(signal.timestamp)}
            </Text>
            <Text style={styles.evidenceBody} numberOfLines={8}>
              {signal.content.trim()}
            </Text>
          </View>
        ))}
      </View>
      {reviewers && reviewers.content.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Reviewers</Text>
          {reviewers.content.map((reviewer) => (
            <Text
              key={reviewer.github_login ?? reviewer.github_name ?? "?"}
              style={styles.reviewer}
            >
              {reviewer.github_name ?? reviewer.github_login ?? "Unknown"}
            </Text>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

export function CardButton({
  label,
  onPress,
  primary,
  disabled,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        primary && styles.buttonPrimary,
        (pressed || disabled) && { opacity: 0.5 },
      ]}
    >
      <Text style={[styles.buttonText, primary && styles.buttonTextPrimary]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  summary: { gap: 10 },
  source: {
    fontFamily: fonts.sansMedium,
    fontSize: 13,
    color: colors.inkMute,
  },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  priority: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  priorityText: { fontFamily: fonts.sansBold, fontSize: 12 },
  tag: {
    fontFamily: fonts.mono,
    fontSize: 12,
    color: colors.inkSoft,
    backgroundColor: colors.code,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 6,
    overflow: "hidden",
  },
  title: {
    fontFamily: fonts.sansBold,
    fontSize: 22,
    lineHeight: 28,
    color: colors.ink,
  },
  lede: {
    fontFamily: fonts.sans,
    fontSize: 16,
    lineHeight: 23,
    color: colors.inkSoft,
  },
  meta: { fontFamily: fonts.sans, fontSize: 13, color: colors.inkMute },
  preview: { gap: 8, marginTop: 6 },
  previewTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.inkMute,
  },
  detail: { flex: 1 },
  detailContent: { gap: 18, paddingBottom: 120 },
  notice: {
    backgroundColor: "rgba(20,144,232,0.10)",
    borderRadius: radius.card,
    padding: 14,
    gap: 4,
  },
  noticeTitle: { fontFamily: fonts.sansSemi, fontSize: 15, color: colors.ink },
  noticeBody: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: colors.inkSoft,
  },
  section: { gap: 8 },
  sectionTitle: { fontFamily: fonts.sansSemi, fontSize: 17, color: colors.ink },
  muted: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkMute },
  evidence: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 12,
    gap: 6,
  },
  evidenceMeta: {
    fontFamily: fonts.sansMedium,
    fontSize: 12,
    color: colors.inkMute,
  },
  evidenceBody: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: colors.ink,
  },
  reviewer: { fontFamily: fonts.sans, fontSize: 15, color: colors.ink },
  button: {
    flex: 1,
    alignItems: "center",
    paddingVertical: 12,
    borderRadius: radius.pill,
    backgroundColor: "rgba(21,21,21,0.06)",
  },
  buttonPrimary: { backgroundColor: colors.accent },
  buttonText: { fontFamily: fonts.sansSemi, fontSize: 15, color: colors.ink },
  buttonTextPrimary: { color: "#FFFFFF" },
});
