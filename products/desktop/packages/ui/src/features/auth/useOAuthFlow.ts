import { mapAuthErrorMessage } from "@posthog/core/auth/authErrors";
import type { DeploymentTarget } from "@posthog/core/auth/schemas";
import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  PREVIEW_DEPLOYMENT,
  type PreviewDeploymentInfo,
} from "@posthog/platform/preview-deployment";
import { useState } from "react";
import { useAuthUiStateStore } from "./authUiStateStore";
import { useLoginMutation } from "./useAuthMutations";

export function useOAuthFlow() {
  const hostClient = useHostTRPCClient();
  const staleRegion = useAuthUiStateStore((s) => s.staleRegion);
  const preview = useService<PreviewDeploymentInfo | null>(PREVIEW_DEPLOYMENT);
  // A preview build has exactly one deployment, so the sign-in target is fixed
  // and the region picker is hidden (see OAuthControls).
  const [region, setRegion] = useState<DeploymentTarget>(
    preview ? "preview" : (staleRegion ?? "us"),
  );
  const loginMutation = useLoginMutation();

  const handleAuth = () => {
    loginMutation.mutate(region);
  };

  const handleRegionChange = (value: DeploymentTarget) => {
    setRegion(value);
    loginMutation.reset();
  };

  const handleCancel = async () => {
    loginMutation.reset();
    await hostClient.oauth.cancelFlow.mutate();
  };

  return {
    region,
    handleAuth,
    handleRegionChange,
    handleCancel,
    isPending: loginMutation.isPending,
    errorMessage: mapAuthErrorMessage(loginMutation.error),
  };
}
