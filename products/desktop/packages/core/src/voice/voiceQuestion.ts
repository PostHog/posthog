import {
  type QuestionItem,
  QuestionMetaSchema,
} from "@posthog/agent/adapters/claude/questions/utils";
import type { PermissionRequest } from "@posthog/shared";

export interface VoiceQuestion {
  id: string;
  toolCallId: string;
  questions: QuestionItem[];
}

export function voiceQuestionFromPermission(
  permission: PermissionRequest | null | undefined,
): VoiceQuestion | null {
  if (permission?.toolCall._meta?.codeToolKind !== "question") return null;
  const parsed = QuestionMetaSchema.safeParse(permission.toolCall._meta);
  if (!parsed.success || parsed.data.questions.length === 0) return null;
  return {
    id: `${permission.taskRunId}:${permission.toolCall.toolCallId}:${permission.receivedAt}`,
    toolCallId: permission.toolCall.toolCallId,
    questions: parsed.data.questions,
  };
}

export interface VoiceQuestionAnswer {
  toolCallId: string;
  questionIndex: number;
  selectedIds: string[];
  customInput: string;
  nextIndex: number;
}

export interface VoiceQuestionDraft {
  activeStep: number;
  stepAnswers: ReadonlyMap<
    number,
    { selectedIds: readonly string[]; customInput: string }
  >;
}

export function voiceQuestionDraftAnswers(
  request: VoiceQuestion,
  draft: VoiceQuestionDraft,
): Record<string, string> {
  const answers: Record<string, string> = {};
  for (const [index, answer] of draft.stepAnswers) {
    const question = request.questions[index];
    if (!question) continue;
    const text = [
      ...answer.selectedIds.map(
        (id) => question.options.find((_, i) => id === `option_${i}`)?.label,
      ),
      answer.customInput.trim(),
    ]
      .filter(Boolean)
      .join(", ");
    if (text) answers[question.question] = text;
  }
  return answers;
}
