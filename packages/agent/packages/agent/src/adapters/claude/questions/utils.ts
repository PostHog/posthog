import type { ToolCallContent, ToolKind } from "@agentclientprotocol/sdk";
import { z } from "zod";
import type { PermissionOption } from "../permissions/permission-options";

export const OPTION_PREFIX = "option_";

export const QuestionOptionSchema = z.object({
  label: z.string(),
  description: z.string().optional(),
});

export const QuestionItemSchema = z.object({
  question: z.string(),
  header: z.string().optional(),
  options: z.array(QuestionOptionSchema),
  multiSelect: z.boolean().optional(),
  completed: z.boolean().optional(),
});

export const QuestionMetaSchema = z.object({
  questions: z.array(QuestionItemSchema),
});

export type QuestionOption = z.infer<typeof QuestionOptionSchema>;
export type QuestionItem = z.infer<typeof QuestionItemSchema>;
export type QuestionMeta = z.infer<typeof QuestionMetaSchema>;

export interface AskUserQuestionInput {
  questions?: QuestionItem[];
  question?: string;
  header?: string;
  options?: QuestionOption[];
  multiSelect?: boolean;
}

export function normalizeAskUserQuestionInput(
  input: AskUserQuestionInput,
): QuestionItem[] | null {
  if (input.questions && input.questions.length > 0) {
    return input.questions;
  }

  if (input.question) {
    return [
      {
        question: input.question,
        header: input.header,
        options: input.options || [],
        multiSelect: input.multiSelect,
      },
    ];
  }

  return null;
}

interface QuestionToolCallData {
  toolCallId: string;
  title: string;
  kind: ToolKind;
  content: ToolCallContent[];
  _meta: {
    codeToolKind: "question";
    questions: QuestionItem[];
  };
}

export function buildQuestionToolCallData(
  questions: QuestionItem[],
): QuestionToolCallData {
  return {
    toolCallId: `question-${Date.now()}`,
    title: questions[0]?.question ?? "Question",
    kind: "other",
    content: [],
    _meta: {
      codeToolKind: "question",
      questions,
    },
  };
}

export function buildQuestionOptions(
  question: QuestionItem,
): PermissionOption[] {
  return question.options.map((opt, idx) => ({
    kind: "allow_once" as const,
    name: opt.label,
    optionId: `${OPTION_PREFIX}${idx}`,
    _meta: opt.description ? { description: opt.description } : undefined,
  }));
}
