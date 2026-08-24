import type { AgentTurnFeedbackSentiment } from "@posthog/shared";
import * as Haptics from "expo-haptics";
import { ThumbsDown, ThumbsUp } from "phosphor-react-native";
import { useCallback } from "react";
import { Pressable, View } from "react-native";
import {
  useTurnFeedback,
  useTurnFeedbackStore,
} from "@/features/tasks/stores/turnFeedbackStore";
import { ANALYTICS_EVENTS, useAnalytics } from "@/lib/analytics";
import { useThemeColors } from "@/lib/theme";

interface TurnFeedbackProps {
  turnId: string;
  taskId?: string | null;
}

export function TurnFeedback({ turnId, taskId }: TurnFeedbackProps) {
  const themeColors = useThemeColors();
  const analytics = useAnalytics();
  const sentiment = useTurnFeedback(turnId);
  const setTurnFeedback = useTurnFeedbackStore((s) => s.setTurnFeedback);

  const rate = useCallback(
    (next: AgentTurnFeedbackSentiment) => {
      if (sentiment === next) return;
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      setTurnFeedback(turnId, next);
      analytics.track(ANALYTICS_EVENTS.AGENT_TURN_FEEDBACK, {
        task_id: taskId ?? null,
        turn_id: turnId,
        sentiment: next,
      });
    },
    [sentiment, setTurnFeedback, analytics, turnId, taskId],
  );

  return (
    <View className="flex-row items-center gap-3">
      <Pressable
        onPress={() => rate("positive")}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel="Good response"
        accessibilityState={{ selected: sentiment === "positive" }}
      >
        <ThumbsUp
          size={14}
          color={themeColors.gray[9]}
          weight={sentiment === "positive" ? "fill" : "regular"}
        />
      </Pressable>
      <Pressable
        onPress={() => rate("negative")}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel="Bad response"
        accessibilityState={{ selected: sentiment === "negative" }}
      >
        <ThumbsDown
          size={14}
          color={themeColors.gray[9]}
          weight={sentiment === "negative" ? "fill" : "regular"}
        />
      </Pressable>
    </View>
  );
}
