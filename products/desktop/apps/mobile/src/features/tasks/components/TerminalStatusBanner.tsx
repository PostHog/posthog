import { Pressable, Text, View } from "react-native";
import type { TerminalStatus } from "../types";

export interface TerminalStatusBannerProps {
  terminalStatus: TerminalStatus;
  lastError?: string | null;
  onRetry?: () => void;
}

export function TerminalStatusBanner({
  terminalStatus,
  lastError,
  onRetry,
}: TerminalStatusBannerProps) {
  const isFailed = terminalStatus === "failed";
  const label =
    terminalStatus === "failed"
      ? "Run failed"
      : terminalStatus === "stopped"
        ? "Run stopped"
        : "Run completed";

  return (
    <View
      className={`mx-4 mt-2 mb-4 rounded-lg px-4 py-3 ${
        isFailed ? "bg-status-error/10" : "bg-status-success/10"
      }`}
    >
      <Text
        className={`font-semibold text-sm ${
          isFailed ? "text-status-error" : "text-status-success"
        }`}
      >
        {label}
      </Text>
      {lastError && (
        <Text className="mt-1 text-gray-11 text-xs">{lastError}</Text>
      )}
      {onRetry && (
        <Pressable
          onPress={onRetry}
          className={`mt-2 self-start rounded-md px-3 py-1.5 ${
            isFailed ? "bg-status-error/20" : "bg-status-success/20"
          }`}
        >
          <Text
            className={`font-medium text-xs ${
              isFailed ? "text-status-error" : "text-status-success"
            }`}
          >
            {isFailed ? "Retry" : "Continue"}
          </Text>
        </Pressable>
      )}
    </View>
  );
}
