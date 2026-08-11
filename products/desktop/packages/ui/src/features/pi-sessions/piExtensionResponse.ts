import type { RpcExtensionUIResponse } from "@posthog/agent/pi/types";
import type { PiExtensionDialogRequest } from "@posthog/core/pi-runtime/piExtensionStore";

export function buildPiExtensionResponse(
  request: PiExtensionDialogRequest,
  value: string | boolean,
): RpcExtensionUIResponse {
  if (request.method === "confirm") {
    return {
      type: "extension_ui_response",
      id: request.id,
      confirmed: value === true,
    };
  }
  return {
    type: "extension_ui_response",
    id: request.id,
    value: typeof value === "string" ? value : "",
  };
}
