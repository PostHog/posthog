import { withTimeout } from "@posthog/shared";
import type { CanvasConnectorPermission } from "./canvasConnectorPermissionService";
import type { CanvasConnectorCallResult } from "./dashboardSchemas";
import type { CanvasConnectorCallInput } from "./freeformSchemas";

const CONNECTOR_IO_TIMEOUT_MS = 30_000;

export async function callCanvasConnector(
  input: CanvasConnectorCallInput,
  invoke: (
    approvalToken: string | undefined,
    signal: AbortSignal,
  ) => Promise<CanvasConnectorCallResult>,
  requestPermission: (
    request: CanvasConnectorPermission,
    signal?: AbortSignal,
  ) => Promise<boolean>,
  signal: AbortSignal,
): Promise<CanvasConnectorCallResult> {
  const invokeWithTimeout = async (
    approvalToken?: string,
  ): Promise<CanvasConnectorCallResult> => {
    signal.throwIfAborted();
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal.addEventListener("abort", cancel, { once: true });
    try {
      const outcome = await withTimeout(
        invoke(approvalToken, controller.signal),
        CONNECTOR_IO_TIMEOUT_MS,
      );
      if (outcome.result === "timeout") {
        controller.abort();
        throw new Error("Canvas connector request timed out");
      }
      signal.throwIfAborted();
      return outcome.value;
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  };

  const result = await invokeWithTimeout();
  if (result.status !== "needs_approval")
    return { ...result, approval_token: undefined };
  if (!result.approval_token)
    throw new Error(
      "This connection cannot accept one-time approval. Try again after updating the server.",
    );
  const approved = await requestPermission(
    { ...input, reason: "tool" },
    signal,
  );
  if (!approved) throw new Error("Tool access was not granted.");
  const approvedResult = await invokeWithTimeout(result.approval_token);
  return { ...approvedResult, approval_token: undefined };
}
