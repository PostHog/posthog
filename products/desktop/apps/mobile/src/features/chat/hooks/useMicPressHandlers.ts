import { useCallback, useRef } from "react";

interface MicPressHandlersArgs {
  isRecording: boolean;
  isTranscribing: boolean;
  /** Whether the button currently shows the mic affordance. Guards the
   *  hold-to-record gesture so holding the same button while it acts as a
   *  send button can't start a recording. */
  holdToRecordEnabled: boolean;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  cancelRecording: () => Promise<void>;
}

/**
 * Gesture handlers for a combined mic button supporting both interaction
 * models:
 *
 * - tap starts, tap again stops (the original toggle);
 * - press-and-hold records for the duration of the hold, releasing stops —
 *   the walkie-talkie gesture people instinctively try. Without an explicit
 *   handler this did nothing at all, because a Pressable with `onLongPress`
 *   suppresses `onPress` for held presses.
 *
 * Long-pressing while a tap-started recording is running keeps the original
 * meaning: cancel.
 */
export function useMicPressHandlers({
  isRecording,
  isTranscribing,
  holdToRecordEnabled,
  startRecording,
  stopRecording,
  cancelRecording,
}: MicPressHandlersArgs) {
  const heldRef = useRef(false);

  const onMicPress = useCallback(async () => {
    if (isRecording) {
      await stopRecording();
    } else if (!isTranscribing) {
      await startRecording();
    }
  }, [isRecording, isTranscribing, startRecording, stopRecording]);

  const onMicLongPress = useCallback(async () => {
    if (isRecording) {
      await cancelRecording();
      return;
    }
    if (!holdToRecordEnabled || isTranscribing) return;
    heldRef.current = true;
    await startRecording();
  }, [
    isRecording,
    isTranscribing,
    holdToRecordEnabled,
    startRecording,
    cancelRecording,
  ]);

  const onMicPressOut = useCallback(async () => {
    if (!heldRef.current) return;
    heldRef.current = false;
    await stopRecording();
  }, [stopRecording]);

  return { onMicPress, onMicLongPress, onMicPressOut };
}
