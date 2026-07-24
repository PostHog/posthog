import {
  ChatCircle,
  CheckCircle,
  CircleDashed,
  RadioButton,
} from "phosphor-react-native";
import { useState } from "react";
import {
  Pressable,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import type { ToolStatus } from "@/features/chat";
import { useThemeColors } from "@/lib/theme";

interface QuestionOption {
  label: string;
  description?: string;
}

interface QuestionItem {
  question: string;
  header?: string;
  options: QuestionOption[];
  multiSelect?: boolean;
}

interface ToolData {
  toolName: string;
  toolCallId: string;
  status: ToolStatus;
  args?: Record<string, unknown>;
  result?: unknown;
}

interface PermissionResponseArgs {
  toolCallId: string;
  optionId: string;
  answers?: Record<string, string>;
  customInput?: string;
  displayText: string;
}

interface QuestionCardProps {
  toolData: ToolData;
  onSendPermissionResponse?: (args: PermissionResponseArgs) => void;
}

function extractQuestions(args?: Record<string, unknown>): QuestionItem[] {
  if (!args) return [];
  // Questions may be at top level or nested under input
  const raw =
    args.questions ?? (args.input as Record<string, unknown>)?.questions;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (q): q is QuestionItem =>
      q != null &&
      typeof q === "object" &&
      typeof (q as QuestionItem).question === "string" &&
      Array.isArray((q as QuestionItem).options),
  );
}

function extractAnswer(result: unknown): string | null {
  if (typeof result === "string") return result;
  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;
    if (typeof obj.answer === "string") return obj.answer;
    if (typeof obj.answers === "object" && obj.answers) {
      const answers = obj.answers as Record<string, string>;
      return Object.values(answers).join(", ");
    }
    if (typeof obj.text === "string") return obj.text;
    if (typeof obj.content === "string") return obj.content;
  }
  return null;
}

export function QuestionCard({
  toolData,
  onSendPermissionResponse,
}: QuestionCardProps) {
  const themeColors = useThemeColors();
  const questions = extractQuestions(toolData.args);
  const isCompleted =
    toolData.status === "completed" || toolData.status === "error";

  if (questions.length === 0) {
    return null;
  }

  if (isCompleted) {
    const answer = extractAnswer(toolData.result);
    return (
      <View className="mx-4 my-1 rounded-lg border border-gray-6 bg-gray-2">
        <View className="flex-row items-center gap-2 px-3 py-2">
          <ChatCircle size={14} color={themeColors.gray[9]} />
          <Text
            className="flex-1 font-mono text-[12px] text-gray-11"
            numberOfLines={1}
          >
            {questions[0]?.header ?? "Question"}
          </Text>
        </View>
        <View className="border-gray-6 border-t px-3 py-2">
          <Text className="font-mono text-[12px] text-gray-9" numberOfLines={2}>
            {questions[0]?.question}
          </Text>
          {answer && (
            <View className="mt-1.5 flex-row items-start gap-1.5">
              <CheckCircle
                size={12}
                color={themeColors.status.success}
                weight="fill"
              />
              <Text className="flex-1 font-mono text-[12px] text-status-success">
                {answer}
              </Text>
            </View>
          )}
        </View>
      </View>
    );
  }

  return (
    <InteractiveQuestion
      questions={questions}
      toolCallId={toolData.toolCallId}
      onSendPermissionResponse={onSendPermissionResponse}
    />
  );
}

function InteractiveQuestion({
  questions,
  toolCallId,
  onSendPermissionResponse,
}: {
  questions: QuestionItem[];
  toolCallId: string;
  onSendPermissionResponse?: (args: PermissionResponseArgs) => void;
}) {
  const themeColors = useThemeColors();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedOptions, setSelectedOptions] = useState<
    Map<number, Set<string>>
  >(new Map());
  const [otherTexts, setOtherTexts] = useState<Map<number, string>>(new Map());
  const [showOtherInput, setShowOtherInput] = useState<Map<number, boolean>>(
    new Map(),
  );

  const question = questions[currentIndex];
  if (!question) return null;

  const isMultiSelect = question.multiSelect ?? false;
  const isLastQuestion = currentIndex === questions.length - 1;
  const selected = selectedOptions.get(currentIndex) ?? new Set<string>();
  const otherText = otherTexts.get(currentIndex) ?? "";
  const isOtherShown = showOtherInput.get(currentIndex) ?? false;
  const hasSelection = selected.size > 0 || otherText.trim().length > 0;

  const toggleOption = (label: string) => {
    const newSelected = new Map(selectedOptions);
    const current = new Set(selected);

    if (isMultiSelect) {
      if (current.has(label)) {
        current.delete(label);
      } else {
        current.add(label);
      }
    } else {
      if (current.has(label)) {
        current.clear();
      } else {
        current.clear();
        current.add(label);
      }
      // Clear "Other" when selecting a preset option
      const newOther = new Map(showOtherInput);
      newOther.set(currentIndex, false);
      setShowOtherInput(newOther);
      const newTexts = new Map(otherTexts);
      newTexts.set(currentIndex, "");
      setOtherTexts(newTexts);
    }

    newSelected.set(currentIndex, current);
    setSelectedOptions(newSelected);
  };

  const toggleOther = () => {
    const newOther = new Map(showOtherInput);
    const isNowShown = !isOtherShown;
    newOther.set(currentIndex, isNowShown);
    setShowOtherInput(newOther);

    if (!isMultiSelect && isNowShown) {
      // Clear preset selections when choosing "Other" in single-select
      const newSelected = new Map(selectedOptions);
      newSelected.set(currentIndex, new Set());
      setSelectedOptions(newSelected);
    }
  };

  const handleSubmit = () => {
    const parts: string[] = [];
    for (const label of selected) {
      parts.push(label);
    }
    const trimmedOther = otherText.trim();
    if (trimmedOther) {
      parts.push(trimmedOther);
    }
    const answer = parts.join(", ");

    if (!isLastQuestion) {
      setCurrentIndex(currentIndex + 1);
      return;
    }

    if (!answer || !onSendPermissionResponse) return;

    // Derive the ACP optionId the agent is expecting. Options are built
    // server-side (buildQuestionOptions in packages/agent) as
    // `${OPTION_PREFIX}${idx}` where OPTION_PREFIX is "option_". If the
    // user only typed into "Other", fall back to option_0 — the answers
    // map carries the actual content for the agent.
    const firstSelectedLabel = parts[0];
    const selectedIdx = question.options.findIndex(
      (o) => o.label === firstSelectedLabel,
    );
    const optionIdx = selectedIdx >= 0 ? selectedIdx : 0;
    const optionId = `option_${optionIdx}`;

    onSendPermissionResponse({
      toolCallId,
      optionId,
      answers: { [question.question]: answer },
      customInput: trimmedOther || undefined,
      displayText: answer,
    });
  };

  return (
    <View className="mx-4 my-1 rounded-lg border border-accent-6 bg-gray-2">
      {/* Header */}
      <View className="flex-row items-center gap-2 border-gray-6 border-b px-3 py-2">
        <ChatCircle size={14} color={themeColors.accent[9]} />
        <Text className="font-mono text-[12px] text-gray-11">
          {question.header ?? "Question"}
        </Text>
        {questions.length > 1 && (
          <Text className="font-mono text-[11px] text-gray-8">
            {currentIndex + 1}/{questions.length}
          </Text>
        )}
      </View>

      {/* Question text */}
      <View className="px-3 pt-3 pb-2">
        <Text className="font-mono text-[13px] text-gray-12 leading-5">
          {question.question}
        </Text>
      </View>

      {/* Options */}
      <View className="px-3 pb-2">
        {question.options.map((option) => {
          const isSelected = selected.has(option.label);
          return (
            <Pressable
              key={option.label}
              onPress={() => toggleOption(option.label)}
              className={`mb-1.5 rounded-lg border px-3 py-2.5 ${
                isSelected
                  ? "border-accent-8 bg-accent-3"
                  : "border-gray-6 bg-gray-3"
              }`}
            >
              <View className="flex-row items-center gap-2">
                {isMultiSelect ? (
                  isSelected ? (
                    <CheckCircle
                      size={16}
                      color={themeColors.accent[9]}
                      weight="fill"
                    />
                  ) : (
                    <CircleDashed size={16} color={themeColors.gray[8]} />
                  )
                ) : isSelected ? (
                  <RadioButton
                    size={16}
                    color={themeColors.accent[9]}
                    weight="fill"
                  />
                ) : (
                  <CircleDashed size={16} color={themeColors.gray[8]} />
                )}
                <Text
                  className={`flex-1 font-mono text-[13px] ${
                    isSelected ? "text-accent-11" : "text-gray-12"
                  }`}
                >
                  {option.label}
                </Text>
              </View>
              {option.description && (
                <Text className="mt-1 ml-6 font-mono text-[11px] text-gray-9 leading-4">
                  {option.description}
                </Text>
              )}
            </Pressable>
          );
        })}

        {/* Other option */}
        <Pressable
          onPress={toggleOther}
          className={`mb-1.5 rounded-lg border px-3 py-2.5 ${
            isOtherShown
              ? "border-accent-8 bg-accent-3"
              : "border-gray-6 bg-gray-3"
          }`}
        >
          <Text
            className={`font-mono text-[13px] ${
              isOtherShown ? "text-accent-11" : "text-gray-9"
            }`}
          >
            Other...
          </Text>
        </Pressable>

        {isOtherShown && (
          <TextInput
            className="mb-1.5 rounded-lg border border-gray-6 bg-gray-3 px-3 py-2.5 font-mono text-[13px] text-gray-12"
            placeholder="Type your answer..."
            placeholderTextColor={themeColors.gray[8]}
            value={otherText}
            onChangeText={(text) => {
              const newTexts = new Map(otherTexts);
              newTexts.set(currentIndex, text);
              setOtherTexts(newTexts);
            }}
            multiline
            autoFocus
          />
        )}
      </View>

      {/* Submit */}
      <View className="border-gray-6 border-t px-3 py-2.5">
        <TouchableOpacity
          onPress={handleSubmit}
          disabled={!hasSelection}
          className={`items-center rounded-lg px-4 py-2.5 ${
            hasSelection ? "bg-accent-9" : "bg-gray-4"
          }`}
          activeOpacity={0.7}
        >
          <Text
            className={`font-medium font-mono text-[13px] ${
              hasSelection ? "text-accent-contrast" : "text-gray-8"
            }`}
          >
            {isLastQuestion ? "Submit" : "Next"}
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}
