import type { CanvasConnectorPermission } from "./canvasConnectorPermissionService";
import type { CanvasConnectorCallResult } from "./dashboardSchemas";
import type { CanvasConnectorCallInput } from "./freeformSchemas";

export async function callCanvasConnector(
  input: CanvasConnectorCallInput,
  invoke: (approved?: boolean) => Promise<CanvasConnectorCallResult>,
  requestPermission: (
    request: CanvasConnectorPermission,
    signal?: AbortSignal,
  ) => Promise<boolean>,
  signal: AbortSignal,
): Promise<CanvasConnectorCallResult> {
  signal.throwIfAborted();
  const result = await invoke();
  if (result.status !== "needs_approval") return result;
  const approved = await requestPermission(
    { ...input, reason: "tool" },
    signal,
  );
  if (!approved) throw new Error("Tool access was not granted.");
  signal.throwIfAborted();
  return invoke(true);
}
