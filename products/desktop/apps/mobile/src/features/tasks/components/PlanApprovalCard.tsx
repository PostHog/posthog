import {
  ArrowsClockwise,
  ChatCircle,
  CheckCircle,
} from "phosphor-react-native";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { MarkdownText, type ToolStatus } from "@/features/chat";
import { useThemeColors } from "@/lib/theme";
import type { CloudPendingPermissionRequest } from "../types";

interface ToolData {
  toolCallId: string;
  status: ToolStatus;
}

interface PermissionResponseArgs {
  toolCallId: string;
  optionId: string;
  answers?: Record<string, string>;
  customInput?: string;
  displayText: string;
}

interface PlanApprovalCardProps {
  toolData: ToolData;
  permission?: CloudPendingPermissionRequest;
  onSendPermissionResponse?: (args: PermissionResponseArgs) => void;
}

function optionMeta(option: CloudPendingPermissionRequest["options"][number]) {
  return option._meta as
    | {
        customInput?: boolean;
        description?: string;
      }
    | undefined;
}

function isRejectOption(
  option?: CloudPendingPermissionRequest["options"][number],
) {
  if (!option) return false;
  return option.kind.startsWith("reject") || option.optionId.includes("reject");
}

function extractTextContent(item: unknown): string | null {
  if (!item || typeof item !== "object") return null;

  const record = item as Record<string, unknown>;
  if (typeof record.text === "string") {
    return record.text;
  }

  if (!record.content || typeof record.content !== "object") {
    return null;
  }

  const content = record.content as Record<string, unknown>;
  return typeof content.text === "string" ? content.text : null;
}

function extractPlanText(
  permission?: CloudPendingPermissionRequest,
): string | null {
  const rawPlan = permission?.toolCall.rawInput?.plan;
  if (typeof rawPlan === "string" && rawPlan.trim().length > 0) {
    return rawPlan;
  }

  for (const item of permission?.toolCall.content ?? []) {
    const text = extractTextContent(item);
    if (text?.trim()) {
      return text;
    }
  }

  return null;
}

export function PlanApprovalCard({
  toolData,
  permission,
  onSendPermissionResponse,
}: PlanApprovalCardProps) {
  const themeColors = useThemeColors();
  const [selectedCustomOptionId, setSelectedCustomOptionId] = useState<
    string | null
  >(null);
  const [customInput, setCustomInput] = useState("");

  const response = permission?.response;
  const planText = useMemo(() => extractPlanText(permission), [permission]);
  const selectedOption = useMemo(
    () =>
      permission?.options.find(
        (option) => option.optionId === response?.optionId,
      ),
    [permission?.options, response?.optionId],
  );
  const isResolved =
    !!response ||
    toolData.status === "completed" ||
    toolData.status === "error";

  if (!permission) {
    return null;
  }

  const submitOption = (
    optionId: string,
    displayText: string,
    nextCustomInput?: string,
  ) => {
    if (!onSendPermissionResponse) return;
    onSendPermissionResponse({
      toolCallId: toolData.toolCallId,
      optionId,
      displayText,
      ...(nextCustomInput ? { customInput: nextCustomInput } : {}),
    });
  };

  const handleCustomSubmit = () => {
    const trimmed = customInput.trim();
    if (!selectedCustomOptionId || !trimmed) return;
    submitOption(selectedCustomOptionId, trimmed, trimmed);
  };

  const responseText =
    response?.customInput?.trim() ||
    selectedOption?.name ||
    response?.displayText ||
    null;
  const resolvedAsReject = isRejectOption(selectedOption);

  return (
    <View className="mx-4 my-1 rounded-lg border border-accent-6 bg-gray-2">
      <View className="flex-row items-center gap-2 border-gray-6 border-b px-3 py-2">
        <ArrowsClockwise size={14} color={themeColors.accent[9]} />
        <Text className="font-mono text-[12px] text-gray-11">
          Implementation Plan
        </Text>
      </View>

      <View className="px-3 pt-3 pb-2">
        <Text className="font-mono text-[13px] text-gray-12 leading-5">
          Approve this plan to proceed?
        </Text>
      </View>

      {planText && (
        <View className="px-3 pb-3">
          <View className="overflow-hidden rounded-lg border border-accent-6 bg-accent-3/40">
            <ScrollView
              className="max-h-[320px]"
              nestedScrollEnabled
              showsVerticalScrollIndicator={false}
            >
              <View className="px-3 py-3">
                <MarkdownText content={planText} />
              </View>
            </ScrollView>
          </View>
        </View>
      )}

      {isResolved ? (
        <View className="px-3 pb-3">
          <View className="flex-row items-start gap-2 rounded-lg border border-gray-6 bg-gray-3 px-3 py-2.5">
            {resolvedAsReject ? (
              <ChatCircle size={14} color={themeColors.gray[11]} />
            ) : (
              <CheckCircle
                size={14}
                color={themeColors.status.success}
                weight="fill"
              />
            )}
            <View className="flex-1">
              <Text
                className={`font-mono text-[12px] ${
                  resolvedAsReject ? "text-gray-11" : "text-status-success"
                }`}
              >
                {resolvedAsReject ? "Sent back with guidance" : "Plan approved"}
              </Text>
              {responseText && (
                <Text className="mt-1 font-mono text-[12px] text-gray-10 leading-4">
                  {responseText}
                </Text>
              )}
            </View>
          </View>
        </View>
      ) : (
        <View className="px-3 pb-3">
          {permission.options.map((option) => {
            const meta = optionMeta(option);
            const usesCustomInput = meta?.customInput === true;
            const isCustomSelected = selectedCustomOptionId === option.optionId;

            return (
              <View key={option.optionId} className="mb-2 last:mb-0">
                <Pressable
                  onPress={() => {
                    if (usesCustomInput) {
                      setSelectedCustomOptionId((current) =>
                        current === option.optionId ? null : option.optionId,
                      );
                      return;
                    }
                    submitOption(option.optionId, option.name);
                  }}
                  className={`rounded-lg border px-3 py-2.5 ${
                    isCustomSelected
                      ? "border-accent-8 bg-accent-3"
                      : "border-gray-6 bg-gray-3"
                  }`}
                >
                  <Text
                    className={`font-mono text-[13px] ${
                      isCustomSelected ? "text-accent-11" : "text-gray-12"
                    }`}
                  >
                    {option.name}
                  </Text>
                  {meta?.description && (
                    <Text className="mt-1 font-mono text-[11px] text-gray-9 leading-4">
                      {meta.description}
                    </Text>
                  )}
                </Pressable>

                {usesCustomInput && isCustomSelected && (
                  <View className="mt-2 rounded-lg border border-gray-6 bg-background px-3 py-3">
                    <TextInput
                      className="min-h-[88px] font-mono text-[13px] text-gray-12"
                      placeholder="Type here to tell the agent what to do differently"
                      placeholderTextColor={themeColors.gray[9]}
                      value={customInput}
                      onChangeText={setCustomInput}
                      multiline
                      textAlignVertical="top"
                    />
                    <Pressable
                      onPress={handleCustomSubmit}
                      disabled={!customInput.trim()}
                      className={`mt-3 rounded-lg px-3 py-2 ${
                        customInput.trim() ? "bg-accent-9" : "bg-gray-4"
                      }`}
                    >
                      <Text
                        className={`text-center font-medium ${
                          customInput.trim()
                            ? "text-accent-contrast"
                            : "text-gray-9"
                        }`}
                      >
                        Send feedback
                      </Text>
                    </Pressable>
                  </View>
                )}
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}
