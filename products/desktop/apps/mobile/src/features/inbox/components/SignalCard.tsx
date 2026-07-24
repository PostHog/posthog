import { Text } from "@components/text";
import {
  EXTERNAL_INBOX_SOURCE_BY_PRODUCT,
  type SourceProduct,
} from "@posthog/shared";
import {
  ArrowSquareOut,
  Bug,
  CaretDown,
  CaretRight,
  ChatCircle,
  CheckCircle,
  Code,
  Compass,
  FirstAid,
  GithubLogo,
  LinkSimple,
  Plug,
  Question,
  Robot,
  WarningCircle,
} from "phosphor-react-native";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { MarkdownText } from "@/features/chat/components/MarkdownText";
import { formatRelativeTime } from "@/lib/format";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import type { Signal, SignalFindingContent } from "../types";
import { sourceLine } from "../utils";

const COLLAPSE_THRESHOLD = 280;

function SourceIcon({
  product,
  size = 14,
  color,
}: {
  product: string;
  size?: number;
  color: string;
}) {
  switch (product) {
    case "error_tracking":
      return <Bug size={size} color={color} />;
    case "github":
      return <GithubLogo size={size} color={color} />;
    case "session_replay":
      return <ChatCircle size={size} color={color} />;
    case "llm_analytics":
      return <Robot size={size} color={color} />;
    case "zendesk":
      return <ChatCircle size={size} color={color} />;
    case "linear":
      return <LinkSimple size={size} color={color} />;
    case "signals_scout":
      return <Compass size={size} color={color} />;
    case "health_checks":
      return <FirstAid size={size} color={color} />;
    default:
      if (EXTERNAL_INBOX_SOURCE_BY_PRODUCT[product as SourceProduct])
        return <Plug size={size} color={color} />;
      return <WarningCircle size={size} color={color} />;
  }
}

function truncateBody(body: string): string {
  if (body.length <= COLLAPSE_THRESHOLD) return body;
  const truncated = body.slice(0, COLLAPSE_THRESHOLD);
  const lastNewline = truncated.lastIndexOf("\n");
  const cut =
    lastNewline > COLLAPSE_THRESHOLD * 0.5 ? lastNewline : COLLAPSE_THRESHOLD;
  let result = truncated.slice(0, cut);
  const fenceCount = (result.match(/^```/gm) || []).length;
  if (fenceCount % 2 !== 0) {
    const lastFence = result.lastIndexOf("```");
    const afterFence = result.slice(lastFence + 3).trim();
    if (!afterFence) {
      result = result.slice(0, lastFence).trimEnd();
    } else {
      result += "\n```";
    }
  }
  return `${result}\n\n…`;
}

function CollapsibleBody({ body }: { body: string }) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  const isLong = body.length > COLLAPSE_THRESHOLD;
  const processed = body.replace(/\\`/g, "`");
  const display = isLong && !expanded ? truncateBody(processed) : processed;

  return (
    <View>
      <MarkdownText content={display} />
      {isLong && (
        <Pressable
          onPress={() => setExpanded((v) => !v)}
          hitSlop={6}
          className="mt-1 flex-row items-center gap-1 self-start py-1 active:opacity-60"
        >
          {expanded ? (
            <CaretDown size={12} color={themeColors.accent[11]} />
          ) : (
            <CaretRight size={12} color={themeColors.accent[11]} />
          )}
          <Text className="font-medium text-[12px] text-accent-11">
            {expanded ? "Show less" : "Show more"}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function CodePathsDisclosure({ paths }: { paths: string[] }) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  if (paths.length === 0) return null;

  return (
    <View className="mt-2 border-gray-5 border-t pt-2">
      <Pressable
        onPress={() => setExpanded((v) => !v)}
        hitSlop={6}
        className="flex-row items-center gap-1 self-start py-1 active:opacity-60"
      >
        {expanded ? (
          <CaretDown size={12} color={themeColors.gray[11]} />
        ) : (
          <CaretRight size={12} color={themeColors.gray[11]} />
        )}
        <Code size={12} color={themeColors.gray[11]} />
        <Text className="font-medium text-[12px] text-gray-11">
          Relevant code ({paths.length})
        </Text>
      </Pressable>
      {expanded && (
        <View className="mt-1 gap-1 pl-[18px]">
          {paths.map((raw) => {
            const trimmed = raw.trim();
            const parenIdx = trimmed.indexOf(" (");
            const filePath =
              parenIdx >= 0 ? trimmed.slice(0, parenIdx) : trimmed;
            const comment = parenIdx >= 0 ? trimmed.slice(parenIdx + 1) : null;
            return (
              <Text key={raw} className="text-[11px]">
                <Text className="font-mono text-[11px] text-gray-12">
                  {filePath}
                </Text>
                {comment && (
                  <Text className="text-[11px] text-gray-9"> {comment}</Text>
                )}
              </Text>
            );
          })}
        </View>
      )}
    </View>
  );
}

function VerifiedBadge({ verified }: { verified: boolean }) {
  const themeColors = useThemeColors();
  const color = verified ? themeColors.status.success : themeColors.gray[9];
  const Icon = verified ? CheckCircle : Question;
  return (
    <View className="flex-row items-center gap-1">
      <Icon size={12} color={color} weight={verified ? "fill" : "bold"} />
      <Text className="text-[11px]" style={{ color }}>
        {verified ? "Verified" : "Unverified"}
      </Text>
    </View>
  );
}

interface SignalCardProps {
  signal: Signal;
  finding?: SignalFindingContent;
}

export function SignalCard({ signal, finding }: SignalCardProps) {
  const themeColors = useThemeColors();
  const verified = finding?.verified;
  const codePaths = finding?.relevant_code_paths ?? [];

  const extra = signal.extra ?? {};
  const issueUrl =
    typeof extra.html_url === "string" ? (extra.html_url as string) : null;
  const issueNumber =
    typeof extra.number === "number" ? (extra.number as number) : null;
  const ticketUrl =
    typeof extra.url === "string" ? (extra.url as string) : null;

  const externalUrl = issueUrl ?? ticketUrl ?? null;

  const timestampMs = signal.timestamp ? Date.parse(signal.timestamp) : NaN;
  const hasTimestamp = !Number.isNaN(timestampMs) && timestampMs <= Date.now();

  return (
    <View className="overflow-hidden rounded-xl border border-gray-6 bg-gray-1 p-3">
      {/* Header */}
      <View className="mb-2 flex-row items-center gap-2">
        <SourceIcon
          product={signal.source_product}
          color={themeColors.gray[10]}
        />
        <Text
          className="min-w-0 shrink font-medium text-[13px] text-gray-10"
          numberOfLines={1}
        >
          {sourceLine(signal)}
        </Text>
        <View className="flex-1" />
        {hasTimestamp && (
          <Text className="shrink-0 text-[11px] text-gray-10">
            {formatRelativeTime(timestampMs)}
          </Text>
        )}
        {verified !== undefined && <VerifiedBadge verified={verified} />}
      </View>

      {/* Body */}
      <CollapsibleBody body={signal.content} />

      {/* Footer meta (lightweight, no source-specific extras for v1) */}
      {(issueNumber !== null || externalUrl) && (
        <View className="mt-2 flex-row items-center gap-3">
          {issueNumber !== null && (
            <Text className="font-medium text-[11px] text-gray-10">
              #{issueNumber}
            </Text>
          )}
          <View className="flex-1" />
          {externalUrl && (
            <Pressable
              onPress={() => openExternalUrl(externalUrl)}
              hitSlop={6}
              className="flex-row items-center gap-1 active:opacity-60"
            >
              <Text className="text-[11px] text-gray-10">Open</Text>
              <ArrowSquareOut size={12} color={themeColors.gray[10]} />
            </Pressable>
          )}
        </View>
      )}

      <CodePathsDisclosure paths={codePaths} />
    </View>
  );
}
