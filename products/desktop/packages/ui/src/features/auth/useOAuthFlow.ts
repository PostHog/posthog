import { mapAuthErrorMessage } from "@posthog/core/auth/authErrors";
import { useHostTRPCClient } from "@posthog/host-router/react";
import type { CloudRegion } from "@posthog/shared";
import { useEffect, useState } from "react";
import { useAuthUiStateStore } from "./authUiStateStore";
import { useLoginMutation } from "./useAuthMutations";

export function useOAuthFlow() {
  const hostClient = useHostTRPCClient();
  const staleRegion = useAuthUiStateStore((s) => s.staleRegion);
  const setSelectedRegion = useAuthUiStateStore((s) => s.setSelectedRegion);
  const [region, setRegion] = useState<CloudRegion>(staleRegion ?? "us");

  useEffect(() => {
    setSelectedRegion(region);
  }, [region, setSelectedRegion]);
  const loginMutation = useLoginMutation();

  const handleAuth = () => {
    loginMutation.mutate(region);
  };

  const handleRegionChange = (value: CloudRegion) => {
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
