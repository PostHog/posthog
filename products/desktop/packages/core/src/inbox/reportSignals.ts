import type { Signal } from "@posthog/shared/domain-types";

function isSessionProblemSignal(signal: Signal): boolean {
  return (
    signal.source_product === "session_replay" &&
    signal.source_type === "session_problem"
  );
}

export interface PartitionedSignals {
  evidence: Signal[];
  signals: Signal[];
}

export function partitionSessionProblemSignals(
  allSignals: Signal[],
): PartitionedSignals {
  const evidence: Signal[] = [];
  const signals: Signal[] = [];
  for (const signal of allSignals) {
    if (isSessionProblemSignal(signal)) {
      evidence.push(signal);
    } else {
      signals.push(signal);
    }
  }
  return { evidence, signals };
}
