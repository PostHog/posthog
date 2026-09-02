import { Alert } from "react-native";

export function confirmArchiveRunningTask(
  taskTitle: string,
  onConfirm: () => void,
): void {
  Alert.alert(
    "Archive running task?",
    `"${taskTitle}" is still running. Archiving it now will stop the agent. You can unarchive it later.`,
    [
      { text: "Cancel", style: "cancel" },
      { text: "Archive", style: "destructive", onPress: onConfirm },
    ],
  );
}

export function confirmStopRun(onConfirm: () => void): void {
  Alert.alert(
    "Stop this run?",
    "This cancels the running agent. You can start a new run afterwards.",
    [
      { text: "Cancel", style: "cancel" },
      { text: "Stop", style: "destructive", onPress: onConfirm },
    ],
  );
}
