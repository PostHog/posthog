import type { SessionActivityEvent } from "@posthog/core/sessions/sessionActivity";
import { voiceConversationContext } from "@posthog/core/voice/conversationContext";
import type { VoiceState } from "@posthog/core/voice/schemas";
import {
  ANALYTICS_EVENTS,
  VOICE_CONVERSATION_FLAG,
  type VoiceConversationEndedProperties,
} from "@posthog/shared";
import { useFocusEffect } from "expo-router";
import { useFeatureFlag, usePostHog } from "posthog-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Platform } from "react-native";
import { useUserQuery } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { createVoiceSession } from "./createVoiceSession";
import { VoiceControls } from "./VoiceControls";

export interface VoiceConversationProps {
  taskId: string;
  events: readonly SessionActivityEvent[];
  pending: boolean;
  onSend(text: string): Promise<boolean>;
  disabled?: boolean;
  onActiveChange?(active: boolean): void;
}

function ActiveVoiceConversation(
  props: VoiceConversationProps,
): React.JSX.Element {
  const [state, setState] = useState<VoiceState>("idle");
  const posthog = usePostHog();
  const latest = useRef({ props, posthog });
  latest.current = { props, posthog };
  const session = useMemo(
    () =>
      createVoiceSession({
        createSession: (sdp, signal) =>
          getPostHogApiClient().createTaskVoiceSession(
            props.taskId,
            sdp,
            voiceConversationContext(latest.current.props.events).context,
            signal,
          ),
        sendMessage: (text) => latest.current.props.onSend(text),
        onState: (next) => {
          setState(next);
          latest.current.props.onActiveChange?.(
            next === "connecting" || next === "connected" || next === "closing",
          );
          if (next === "connected")
            latest.current.posthog?.capture(
              ANALYTICS_EVENTS.VOICE_CONVERSATION_STARTED,
              { task_id: props.taskId },
            );
        },
        onEnded: ({ sessionId, seconds, finalized, failed }) => {
          const properties: VoiceConversationEndedProperties = {
            task_id: props.taskId,
            voice_duration_seconds: seconds,
            finalized,
            failed,
          };
          latest.current.posthog?.capture(
            ANALYTICS_EVENTS.VOICE_CONVERSATION_ENDED,
            { ...properties },
          );
          if (sessionId)
            latest.current.posthog?.capture("$ai_generation", {
              $ai_model: "gpt-live-1",
              $ai_provider: "openai",
              $ai_session_id: props.taskId,
              $ai_trace_id: sessionId,
              $ai_span_id: sessionId,
              $ai_stream: true,
              $ai_is_error: failed,
              voice_duration_seconds: seconds,
              voice_usage_finalized: finalized,
            });
        },
      }),
    [props.taskId],
  );
  useEffect(() => {
    const { reply, replyKey } = voiceConversationContext(props.events);
    session.updateReply(reply, !props.pending, replyKey);
  }, [session, props.events, props.pending]);
  useFocusEffect(useCallback(() => () => session.stop(), [session]));
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      if (next !== "active") session.stop();
    });
    return () => {
      subscription.remove();
      session.stop();
    };
  }, [session]);
  return (
    <VoiceControls
      state={state}
      disabled={props.disabled}
      onPress={() => {
        if (state === "idle" || state === "error") void session.start();
        else session.stop();
      }}
    />
  );
}

export function VoiceConversationControl(
  props: VoiceConversationProps,
): React.JSX.Element | null {
  const enabled = useFeatureFlag(VOICE_CONVERSATION_FLAG);
  const { data: user } = useUserQuery();
  return Platform.OS !== "web" &&
    enabled === true &&
    user?.is_staff === true ? (
    <ActiveVoiceConversation key={props.taskId} {...props} />
  ) : null;
}
