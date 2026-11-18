export type ComposerPrimaryAction =
  | "send"
  | "stop"
  | "mic"
  | "mic-stop"
  | "disabled";

export function resolveComposerPrimaryAction({
  hasContent,
  disabled,
  isRecording,
  isTranscribing,
  canStop,
  allowSendWhileRunning,
}: {
  hasContent: boolean;
  disabled: boolean;
  isRecording: boolean;
  isTranscribing: boolean;
  canStop: boolean;
  allowSendWhileRunning: boolean;
}): ComposerPrimaryAction {
  if (disabled || isTranscribing) return "disabled";
  if (canStop && (!allowSendWhileRunning || !hasContent)) return "stop";
  if (hasContent && !isRecording) return "send";
  return isRecording ? "mic-stop" : "mic";
}
