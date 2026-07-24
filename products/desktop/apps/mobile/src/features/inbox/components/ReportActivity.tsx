import { Text } from "@components/text";
import { ClockCounterClockwise } from "phosphor-react-native";
import { useMemo } from "react";
import { View } from "react-native";
import { formatRelativeTime } from "@/lib/format";
import { useThemeColors } from "@/lib/theme";
import {
  type ActivityArtefact,
  attributionLabel,
  selectActivityArtefacts,
} from "../activityLog";
import type { ReportArtefact } from "../types";
import { ArtefactCommit } from "./ArtefactCommit";
import { ArtefactTaskRun } from "./ArtefactTaskRun";

function ArtefactRow({
  reportId,
  artefact,
}: {
  reportId: string;
  artefact: ActivityArtefact;
}) {
  const attribution = attributionLabel(artefact);
  const timestampMs = Date.parse(artefact.created_at);

  return (
    <View className="rounded-xl border border-gray-6 bg-gray-1 p-3">
      <View className="mb-1.5 flex-row items-center gap-2">
        <Text className="font-medium text-[12px] text-gray-12">
          {artefact.type === "commit" ? "Commit pushed" : "Task run"}
        </Text>
        <View className="flex-1" />
        {attribution ? (
          <Text className="text-[11px] text-gray-9">by {attribution}</Text>
        ) : null}
        {!Number.isNaN(timestampMs) ? (
          <Text className="text-[11px] text-gray-9">
            {formatRelativeTime(timestampMs)}
          </Text>
        ) : null}
      </View>
      {artefact.type === "commit" ? (
        <ArtefactCommit
          reportId={reportId}
          artefactId={artefact.id}
          content={artefact.content}
        />
      ) : (
        <ArtefactTaskRun content={artefact.content} />
      )}
    </View>
  );
}

export function ReportActivity({
  reportId,
  artefacts,
}: {
  reportId: string;
  artefacts: ReportArtefact[];
}) {
  const themeColors = useThemeColors();
  const activity = useMemo(
    () => selectActivityArtefacts(artefacts),
    [artefacts],
  );

  if (activity.length === 0) return null;

  return (
    <View className="mb-4">
      <View className="mb-2 flex-row items-center gap-1.5">
        <ClockCounterClockwise size={14} color={themeColors.gray[12]} />
        <Text className="font-semibold text-[14px] text-gray-12">
          Activity ({activity.length})
        </Text>
      </View>
      <View className="gap-2">
        {activity.map((artefact) => (
          <ArtefactRow
            key={artefact.id}
            reportId={reportId}
            artefact={artefact}
          />
        ))}
      </View>
    </View>
  );
}
