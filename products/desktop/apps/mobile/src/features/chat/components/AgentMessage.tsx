import { Brain } from "phosphor-react-native";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { formatRelativeTime } from "@/lib/format";
import { useThemeColors } from "@/lib/theme";
import { usePeriodicRerender } from "../hooks/usePeriodicRerender";
import { getRandomThinkingMessage } from "../utils/thinkingMessages";
import { CopyButton } from "./CopyButton";
import { MarkdownText } from "./MarkdownText";
import { ToolMessage } from "./ToolMessage";

interface AssistantToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  type: "tool_call";
}

interface AgentMessageProps {
  content: string;
  isLoading?: boolean;
  thinkingText?: string;
  toolCalls?: AssistantToolCall[];
  hasHumanMessageAfter?: boolean;
  onOpenTask?: (taskId: string) => void;
  timestamp?: number;
}

interface ReasoningBlockProps {
  content: string;
  isComplete: boolean;
}

function ReasoningBlock({ content, isComplete }: ReasoningBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const themeColors = useThemeColors();

  if (!isComplete) {
    // Show thinking content
    return (
      <View className="px-4 py-0.5">
        <View className="flex-row items-start gap-2">
          <Brain size={12} color={themeColors.gray[9]} />
          <Text className="ml-1 font-mono text-[12px] text-gray-9 leading-4">
            {content}
          </Text>
        </View>
      </View>
    );
  }

  // Show collapsible "Thought" block
  return (
    <View className="px-4 py-0.5">
      <Pressable
        onPress={() => setIsExpanded(!isExpanded)}
        className="flex-row items-center gap-2"
      >
        <Brain size={12} color={themeColors.gray[9]} />
        <Text className="font-mono text-[13px] text-gray-12">Thought</Text>
      </Pressable>
      {isExpanded && (
        <Text className="my-2 ml-5 font-mono text-[12px] text-gray-9 leading-4">
          {content}
        </Text>
      )}
    </View>
  );
}

const THINKING_MESSAGE_INTERVAL_MS = 2000;

export function AgentMessage({
  content,
  isLoading,
  thinkingText,
  toolCalls,
  hasHumanMessageAfter,
  onOpenTask,
  timestamp,
}: AgentMessageProps) {
  usePeriodicRerender(isLoading ? THINKING_MESSAGE_INTERVAL_MS : 0);

  const hasContent = !!content;
  const isComplete = !isLoading && hasContent;

  return (
    <View className="py-2">
      {toolCalls && toolCalls.length > 0 && (
        <View className="mb-1">
          {toolCalls.map((tc) => (
            <ToolMessage
              key={tc.id}
              toolName={tc.name}
              status="completed"
              args={tc.args}
              hasHumanMessageAfter={hasHumanMessageAfter}
              onOpenTask={onOpenTask}
            />
          ))}
        </View>
      )}

      {/* Show reasoning/thinking block if available */}
      {thinkingText && (
        <ReasoningBlock content={thinkingText} isComplete={isComplete} />
      )}

      {/* Show loading state with random thinking message */}
      {isLoading && !content && !thinkingText && (
        <View className="max-w-[95%] px-4 py-1">
          <Text className="font-mono text-[13px] text-gray-9 italic">
            {getRandomThinkingMessage()}
          </Text>
        </View>
      )}

      {content && (
        <View className="max-w-[95%] px-4 py-1">
          <MarkdownText content={content} />
        </View>
      )}

      {!isLoading && (hasContent || timestamp) && (
        <View className="flex-row items-center gap-3 px-4 pt-1">
          {isComplete && <CopyButton text={content} label="Copy message" />}
          {timestamp && (
            <Text className="font-mono text-[10px] text-gray-8">
              {formatRelativeTime(timestamp)}
            </Text>
          )}
        </View>
      )}
    </View>
  );
}
