import { CheckCircle, CircleDashed, XCircle } from "phosphor-react-native";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { PlanEntry } from "../types";

interface PlanStatusBarProps {
  plan: PlanEntry[] | null;
}

function StatusIcon({ status }: { status: string }) {
  const themeColors = useThemeColors();

  switch (status) {
    case "completed":
      return <CheckCircle size={14} color={themeColors.status.success} />;
    case "in_progress":
      return <ActivityIndicator size={12} color={themeColors.accent[9]} />;
    case "failed":
      return <XCircle size={14} color={themeColors.status.error} />;
    default:
      return <CircleDashed size={14} color={themeColors.gray[8]} />;
  }
}

export function PlanStatusBar({ plan }: PlanStatusBarProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const themeColors = useThemeColors();

  const stats = useMemo(() => {
    if (!plan?.length) return null;

    const completed = plan.filter((e) => e.status === "completed").length;
    const total = plan.length;
    const inProgress = plan.find((e) => e.status === "in_progress");
    const allCompleted = completed === total;

    return { completed, total, inProgress, allCompleted };
  }, [plan]);

  if (!stats || stats.allCompleted) return null;

  return (
    <View className="border-gray-6 border-b bg-gray-2">
      <Pressable
        onPress={() => setIsExpanded(!isExpanded)}
        className="flex-row items-center gap-2 px-4 py-2.5"
      >
        <Text className="font-mono text-[12px] text-gray-9">
          {stats.completed}/{stats.total} completed
        </Text>
        {stats.inProgress && (
          <>
            <Text className="text-[12px] text-gray-7">·</Text>
            <ActivityIndicator size={10} color={themeColors.accent[9]} />
            <Text
              className="flex-1 font-mono text-[12px] text-gray-11"
              numberOfLines={1}
            >
              {stats.inProgress.content}
            </Text>
          </>
        )}
      </Pressable>

      {isExpanded && plan && (
        <View className="border-gray-6 border-t px-4 pt-2 pb-2.5">
          {plan.map((entry, index) => (
            <View
              key={`${index}-${entry.content}`}
              className="flex-row items-center gap-2 py-1"
            >
              <StatusIcon status={entry.status} />
              <Text
                className={`flex-1 font-mono text-[12px] ${
                  entry.status === "completed" ? "text-gray-9" : "text-gray-12"
                }`}
                numberOfLines={1}
              >
                {entry.content}
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}
