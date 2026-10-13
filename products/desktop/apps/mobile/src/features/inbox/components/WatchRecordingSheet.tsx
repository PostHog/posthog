import { Text } from "@components/text";
import type { RecordingExport } from "@posthog/api-client/posthog-client";
import { useVideoPlayer, VideoView } from "expo-video";
import { ArrowSquareOut, X } from "phosphor-react-native";
import { useMemo } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  useWindowDimensions,
  View,
} from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { clipTimeForMoment } from "../recordingClipTime";
import { colonOffsetFromSeconds } from "../recordingOffset";

interface WatchRecordingSheetProps {
  visible: boolean;
  clip: RecordingExport | null;
  contentUrl: string | null;
  contentPending: boolean;
  contentUnavailable: boolean;
  seekSeconds?: number | null;
  playerUrl?: string | null;
  onClose: () => void;
}

export function WatchRecordingSheet({
  visible,
  clip,
  contentUrl,
  contentPending,
  contentUnavailable,
  seekSeconds,
  playerUrl,
  onClose,
}: WatchRecordingSheetProps) {
  const { width, height } = useWindowDimensions();

  const targetClipTime = useMemo(() => {
    if (clip == null || seekSeconds == null) return null;
    return clipTimeForMoment(clip, seekSeconds);
  }, [clip, seekSeconds]);
  const momentReachable = seekSeconds == null ? null : targetClipTime != null;
  const momentLabel =
    seekSeconds != null ? colonOffsetFromSeconds(seekSeconds) : null;

  const player = useVideoPlayer(contentUrl, (p) => {
    p.muted = true;
    if (targetClipTime != null) p.currentTime = targetClipTime;
    p.play();
  });

  const seekToMoment = () => {
    if (targetClipTime == null) return;
    const duration = player.duration;
    player.currentTime =
      duration > 0 ? Math.min(targetClipTime, duration) : targetClipTime;
    player.play();
  };

  const videoWidth = Math.min(width - 32, 720);
  const videoHeight = Math.min(videoWidth * (9 / 16), height * 0.6);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <Pressable
        className="flex-1 items-center justify-center bg-black/80 px-4"
        onPress={onClose}
      >
        <Pressable onPress={() => {}} className="w-full max-w-[720px] gap-3">
          <View className="flex-row items-center justify-between">
            <View className="flex-1 pr-3">
              <Text className="font-semibold text-[16px] text-white">
                Session recording
              </Text>
              <Text
                className="mt-0.5 text-[12px] text-white/70"
                numberOfLines={2}
              >
                {describeClipStatus(momentLabel, momentReachable)}
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              className="rounded-full bg-white/10 p-2 active:opacity-70"
              accessibilityLabel="Close"
            >
              <X size={16} color="#ffffff" weight="bold" />
            </Pressable>
          </View>

          <View
            className="items-center justify-center overflow-hidden rounded-xl bg-black"
            style={{ width: videoWidth, height: videoHeight }}
          >
            {contentUnavailable ? (
              <Text className="px-6 text-center text-[13px] text-white/70">
                This clip is no longer available.
              </Text>
            ) : contentPending || contentUrl == null ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <VideoView
                player={player}
                style={{ width: videoWidth, height: videoHeight }}
                nativeControls
                contentFit="contain"
              />
            )}
          </View>

          <View className="flex-row items-center justify-between">
            {momentLabel && momentReachable === true ? (
              <Pressable
                onPress={seekToMoment}
                hitSlop={6}
                className="rounded-full bg-white/10 px-3 py-2 active:opacity-70"
              >
                <Text className="text-[12px] text-white">
                  Back to {momentLabel}
                </Text>
              </Pressable>
            ) : (
              <View />
            )}
            {playerUrl && (
              <Pressable
                onPress={() => openExternalUrl(playerUrl)}
                hitSlop={6}
                className="flex-row items-center gap-1 active:opacity-70"
              >
                <Text className="text-[12px] text-white/80">
                  Open in PostHog
                </Text>
                <ArrowSquareOut size={12} color="#ffffff" />
              </Pressable>
            )}
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function describeClipStatus(
  momentLabel: string | null,
  momentReachable: boolean | null,
): string {
  if (momentLabel == null) return "The rendered clip from this session.";
  if (momentReachable === false)
    return `The clip stops before ${momentLabel}. Open the session in PostHog to reach that moment.`;
  return `The rendered clip, at ${momentLabel} in the session.`;
}
