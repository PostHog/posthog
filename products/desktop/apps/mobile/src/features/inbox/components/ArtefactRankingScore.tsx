import { Text } from "@components/text";
import { humanizeIdentifier } from "@posthog/core/inbox/activityLog";
import {
  formatRankingLift,
  formatRankingProbability,
  rankingLiftBarPercent,
} from "@posthog/core/inbox/rankingFormat";
import type {
  RankingHead,
  RankingScoreContent,
} from "@posthog/shared/domain-types";
import { View } from "react-native";

function RankingHeadRow({ head }: { head: RankingHead }) {
  const tone = head.readable ? "text-gray-12" : "text-gray-10";
  return (
    <View className="flex-row items-center gap-2">
      <Text className={`w-24 text-[12px] ${tone}`} numberOfLines={1}>
        {humanizeIdentifier(head.name)}
      </Text>
      <View className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-gray-4">
        {head.lift !== null ? (
          <View
            className={`h-full rounded-full ${head.readable ? "bg-accent-9" : "bg-gray-8"}`}
            style={{ width: `${rankingLiftBarPercent(head.lift)}%` }}
          />
        ) : null}
        <View className="absolute top-0 bottom-0 left-1/2 w-px bg-gray-9" />
      </View>
      <Text className={`w-10 text-right text-[12px] ${tone}`}>
        {head.lift !== null ? formatRankingLift(head.lift) : ""}
      </Text>
      <Text className="w-11 text-right text-[12px] text-gray-10">
        {formatRankingProbability(head.probability)}
      </Text>
    </View>
  );
}

/** The served model's heads. Dimmed heads have no holdout read yet. */
export function ArtefactRankingScore({
  content,
}: {
  content: RankingScoreContent;
}) {
  const { served } = content;
  const hasUnreadable = served.heads.some((head) => !head.readable);
  return (
    <View className="gap-1">
      {served.status === "skipped" || served.heads.length === 0 ? (
        <Text className="text-[12px] text-gray-10">
          Skipped{served.skip_reason ? `: ${served.skip_reason}` : ""}
        </Text>
      ) : (
        served.heads.map((head) => (
          <RankingHeadRow key={head.name} head={head} />
        ))
      )}
      {hasUnreadable ? (
        <Text className="text-[11px] text-gray-9">
          Dimmed heads have no holdout read yet.
        </Text>
      ) : null}
      <Text className="font-mono text-[11px] text-gray-9" numberOfLines={1}>
        {served.key}
      </Text>
    </View>
  );
}
