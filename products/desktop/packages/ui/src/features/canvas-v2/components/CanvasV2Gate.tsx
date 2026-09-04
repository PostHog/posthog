import { useCanvasesV2Flag } from "@posthog/ui/features/feature-flags/useCanvasesV2Flag";
import { useFeatureFlagsLoaded } from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import { AppPageSkeleton } from "@posthog/ui/router/routeSkeletons";
import { Navigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

export function CanvasV2Gate({ children }: { children: ReactNode }) {
  const enabled = useCanvasesV2Flag();
  const flagsLoaded = useFeatureFlagsLoaded();

  if (enabled) return children;
  if (!flagsLoaded) return <AppPageSkeleton />;
  return <Navigate replace to="/canvases" search={{ canvas: undefined }} />;
}
