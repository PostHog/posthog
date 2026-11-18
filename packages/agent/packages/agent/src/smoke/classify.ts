import {
  classifyAgentError,
  isRetryableUpstreamErrorClassification,
} from "../adapters/error-classification";
import type { TurnOutcome } from "./run-turn";

export type SmokeResult = "pass" | "broken" | "inconclusive" | "infra";

const TRANSIENT_STATUS = /\b(?:error|status|http)\D{0,12}(?:429|5\d\d)\b/i;
const TRANSIENT_TEXT =
  /timed out|overloaded|rate limit|ECONNRESET|ETIMEDOUT|fetch failed|error sending request/i;

const LOCAL_ACP_CLOSED = /^ACP connection closed$/i;

export function classifyFailure(message: string): "broken" | "inconclusive" {
  const cause = message.replace(/^Internal error:\s*/i, "");
  if (LOCAL_ACP_CLOSED.test(cause)) {
    return "broken";
  }
  return TRANSIENT_STATUS.test(cause) ||
    TRANSIENT_TEXT.test(cause) ||
    isRetryableUpstreamErrorClassification(classifyAgentError(cause))
    ? "inconclusive"
    : "broken";
}

export function classifyOutcome(outcome: TurnOutcome): SmokeResult {
  if (outcome.stopReason !== "end_turn") {
    return classifyFailure(outcome.reply);
  }
  return outcome.completedToolCalls > 0 && outcome.replyHasNonce
    ? "pass"
    : "broken";
}
