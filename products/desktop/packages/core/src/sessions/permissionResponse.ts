import type { PermissionRequest } from "@posthog/shared";

const OTHER_OPTION_ID = "_other";
const OTHER_OPTION_ID_ALT = "other";

export function isOtherPermissionOption(optionId: string): boolean {
  return optionId === OTHER_OPTION_ID || optionId === OTHER_OPTION_ID_ALT;
}

export interface PermissionSelectionPlan {
  applyAllowAlwaysUpgrade: boolean;
  respondWithCustomInput: boolean;
  resendPromptText: string | null;
}

export function planPermissionResponse(
  permission: PermissionRequest,
  optionId: string,
  customInput?: string,
): PermissionSelectionPlan {
  const selectedOption = permission.options.find(
    (o) => o.optionId === optionId,
  );
  const isModeSwitch = permission.toolCall?.kind === "switch_mode";
  const applyAllowAlwaysUpgrade =
    selectedOption?.kind === "allow_always" && !isModeSwitch;

  const optionTakesCustomInput =
    isOtherPermissionOption(optionId) ||
    (selectedOption?._meta as { customInput?: boolean } | undefined)
      ?.customInput === true;

  if (customInput && optionTakesCustomInput) {
    return {
      applyAllowAlwaysUpgrade,
      respondWithCustomInput: true,
      resendPromptText: null,
    };
  }

  if (customInput) {
    return {
      applyAllowAlwaysUpgrade,
      respondWithCustomInput: false,
      resendPromptText: customInput,
    };
  }

  return {
    applyAllowAlwaysUpgrade,
    respondWithCustomInput: false,
    resendPromptText: null,
  };
}

interface QuestionMeta {
  codeToolKind?: unknown;
  questions?: unknown;
}

function questionMeta(
  permission: PermissionRequest | undefined,
): QuestionMeta | null {
  const meta = permission?.toolCall?._meta;
  if (!meta || typeof meta !== "object" || Array.isArray(meta)) {
    return null;
  }
  return meta as QuestionMeta;
}

export function isQuestionPermission(
  permission: PermissionRequest | undefined,
): boolean {
  return questionMeta(permission)?.codeToolKind === "question";
}

/**
 * Builds the follow-up prompt that carries a question's selected answer into a
 * resumed run. Once a cloud run has terminalized, its sandbox and the pending
 * permission promise inside it are gone, so a permission_response command has
 * nothing left to resolve. The answer travels as a fresh user message on a
 * resume run instead.
 * Returns null when there is nothing meaningful to carry forward (a plain
 * approval), so callers can drop the response rather than spin a pointless run.
 */
export function formatPermissionAnswerPrompt(
  permission: PermissionRequest | undefined,
  optionId: string,
  customInput?: string,
  answers?: Record<string, string>,
): string | null {
  const selectedAnswers: string[] = [];
  for (const [question, answer] of Object.entries(answers ?? {})) {
    if (question.trim() && answer.trim()) {
      selectedAnswers.push(answer.trim());
    }
  }

  if (selectedAnswers.length === 0) {
    if (!isQuestionPermission(permission)) {
      return null;
    }
    // A question answered without an answers map: free text, or a bare option pick.
    const answerText =
      customInput?.trim() ||
      permission?.options
        .find((option) => option.optionId === optionId)
        ?.name?.trim();
    if (!answerText) {
      return null;
    }
    selectedAnswers.push(answerText);
  } else {
    const extraInput = customInput?.trim();
    if (extraInput && !selectedAnswers.includes(extraInput)) {
      selectedAnswers.push(extraInput);
    }
  }

  if (selectedAnswers.length === 1) {
    return selectedAnswers[0] ?? null;
  }

  return selectedAnswers
    .map((answer, index) => `${index + 1}. ${answer}`)
    .join("\n");
}
