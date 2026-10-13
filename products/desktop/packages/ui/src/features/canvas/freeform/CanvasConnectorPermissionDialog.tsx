import {
  CANVAS_CONNECTOR_PERMISSION_SERVICE,
  type CanvasConnectorPermissionService,
} from "@posthog/core/canvas/canvasConnectorPermissionService";
import { useService } from "@posthog/di/react";
import { useStore } from "zustand";
import { CanvasConnectorPermissionPrompt } from "./CanvasConnectorPermissionPrompt";

export function CanvasConnectorPermissionDialog() {
  const service = useService<CanvasConnectorPermissionService>(
    CANVAS_CONNECTOR_PERMISSION_SERVICE,
  );
  const request = useStore(service.store, (state) => state.pending[0]);
  return (
    <CanvasConnectorPermissionPrompt
      request={request}
      onRespond={(allowed) => {
        if (request) service.respond(request, allowed);
      }}
    />
  );
}
