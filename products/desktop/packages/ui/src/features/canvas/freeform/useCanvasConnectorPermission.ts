import {
  CANVAS_CONNECTOR_PERMISSION_SERVICE,
  type CanvasConnectorPermission,
  type CanvasConnectorPermissionService,
} from "@posthog/core/canvas/canvasConnectorPermissionService";
import { useService } from "@posthog/di/react";
import { useCallback, useEffect, useMemo, useRef } from "react";

export function useCanvasConnectorPermission(
  canvasId: string | undefined,
  versionId: string | null | undefined,
) {
  const service = useService<CanvasConnectorPermissionService>(
    CANVAS_CONNECTOR_PERMISSION_SERVICE,
  );
  const owner = useMemo(
    () => Symbol(`${canvasId}:${versionId}`),
    [canvasId, versionId],
  );
  const activeOwner = useRef<symbol | null>(owner);
  useEffect(() => {
    activeOwner.current = owner;
    return () => {
      activeOwner.current = null;
      service.cancel(owner);
    };
  }, [service, owner]);
  return useCallback(
    (input: CanvasConnectorPermission, signal?: AbortSignal) =>
      activeOwner.current === owner
        ? service.request(owner, input, signal)
        : Promise.resolve(false),
    [service, owner],
  );
}
