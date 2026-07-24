import { Text } from "@components/text";
import { CaretDown, CaretRight } from "phosphor-react-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { shortSha } from "../activityLog";
import { useCommitDiff } from "../hooks/useInboxReports";
import type { CommitContent } from "../types";
import { DiffBlock } from "./DiffBlock";

export function ArtefactCommit({
  reportId,
  artefactId,
  content,
}: {
  reportId: string;
  artefactId: string;
  content: CommitContent;
}) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  const diffQuery = useCommitDiff(reportId, artefactId, expanded);

  return (
    <View>
      <Text className="text-[13px] text-gray-12">{content.message}</Text>
      <Text className="font-mono text-[11px] text-gray-9">
        {shortSha(content.commit_sha)} · {content.repository}@{content.branch}
      </Text>
      {content.note?.trim() ? (
        <Text className="mt-0.5 text-[12px] text-gray-11">{content.note}</Text>
      ) : null}

      <Pressable
        onPress={() => setExpanded((v) => !v)}
        hitSlop={6}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        className="mt-1.5 flex-row items-center gap-1 self-start py-1 active:opacity-60"
      >
        {expanded ? (
          <CaretDown size={12} color={themeColors.gray[11]} />
        ) : (
          <CaretRight size={12} color={themeColors.gray[11]} />
        )}
        <Text className="text-[12px] text-gray-11">
          {expanded ? "Hide diff" : "View diff"}
        </Text>
      </Pressable>

      {expanded ? (
        <View className="mt-1.5">
          {diffQuery.isLoading ? (
            <View className="flex-row items-center gap-2">
              <ActivityIndicator size="small" color={themeColors.gray[9]} />
              <Text className="text-[12px] text-gray-9">Fetching diff…</Text>
            </View>
          ) : diffQuery.isError ? (
            <Text className="text-[12px] text-status-error">
              Couldn’t load the diff.
            </Text>
          ) : diffQuery.data?.diff.trim() ? (
            <>
              <DiffBlock diff={diffQuery.data.diff} />
              {diffQuery.data.truncated ? (
                <Text className="mt-1 text-[11px] text-gray-9">
                  Diff truncated — too large to display in full.
                </Text>
              ) : null}
            </>
          ) : (
            <Text className="text-[12px] text-gray-9">
              No changes recorded for this commit.
            </Text>
          )}
        </View>
      ) : null}
    </View>
  );
}
