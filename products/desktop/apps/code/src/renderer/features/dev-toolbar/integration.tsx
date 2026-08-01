import { toast } from "@posthog/ui/primitives/toast";
import { useTRPC } from "@renderer/trpc/client";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useEffect } from "react";
import { subscribeDevFlagsFromMain, useDevFlagsStore } from "./devFlagsStore";
import { installMainThreadHealth } from "./mainThreadHealth";

export function useDevToolbarIntegration(): void {
  const trpcReact = useTRPC();
  const devMode = useDevFlagsStore((s) => s.devMode);

  useEffect(() => {
    if (!devMode) return;
    const stopHealth = installMainThreadHealth();
    const stopFlags = subscribeDevFlagsFromMain();
    return () => {
      stopHealth();
      stopFlags();
    };
  }, [devMode]);

  useSubscription(
    trpcReact.dev.onDevToast.subscriptionOptions(undefined, {
      enabled: devMode,
      onData: (data) => {
        if (data.variant === "error") {
          toast.error(data.message);
        } else {
          toast.info(data.message);
        }
      },
    }),
  );
}
