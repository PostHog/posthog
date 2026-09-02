import { HostTRPCProvider } from "@posthog/host-router/react";
import { ThemeWrapper } from "@posthog/ui/primitives/ThemeWrapper";
import { WorkspaceClientProvider } from "@posthog/workspace-client/provider";
import {
  hostTrpcClient,
  TRPCProvider,
  trpcClient,
  useTRPC,
} from "@renderer/trpc/client";
import {
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { queryClient } from "@utils/queryClient";
import type React from "react";
import { useCallback, useState } from "react";
import { HotkeysProvider } from "react-hotkeys-hook";

function WorkspaceServerErrorBanner({
  onRetry,
  disabled,
}: {
  onRetry: () => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="alert"
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-3 bg-red-600 px-4 py-2 text-sm text-white"
    >
      <span>The workspace server stopped and could not be restarted.</span>
      <button
        type="button"
        onClick={onRetry}
        disabled={disabled}
        className="rounded bg-white/20 px-2 py-0.5 font-medium hover:bg-white/30 disabled:cursor-not-allowed disabled:opacity-60"
      >
        Retry
      </button>
    </div>
  );
}

function ConnectedWorkspaceProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const trpc = useTRPC();
  const rqClient = useQueryClient();
  const [serverStatus, setServerStatus] = useState<string>("ready");
  const { data: connection } = useQuery(
    trpc.workspaceServer.getConnection.queryOptions(undefined, {
      staleTime: 30_000,
    }),
  );

  const invalidateConnection = useCallback(() => {
    rqClient.invalidateQueries({
      queryKey: trpc.workspaceServer.getConnection.queryKey(),
    });
  }, [rqClient, trpc]);

  const restartServer = useMutation(
    trpc.workspaceServer.restart.mutationOptions(),
  );

  useSubscription(
    trpc.workspaceServer.onConnectionLost.subscriptionOptions(undefined, {
      onData: invalidateConnection,
    }),
  );

  useSubscription(
    trpc.workspaceServer.onStatusChanged.subscriptionOptions(undefined, {
      onData: (data) => {
        setServerStatus(data.status);
        if (data.status === "ready") {
          invalidateConnection();
        }
      },
    }),
  );

  return (
    <WorkspaceClientProvider connection={connection} queryClient={queryClient}>
      {serverStatus === "failed" ? (
        <WorkspaceServerErrorBanner
          onRetry={() =>
            restartServer.mutate(undefined, {
              onSettled: () => invalidateConnection(),
            })
          }
          disabled={restartServer.isPending}
        />
      ) : null}
      {children}
    </WorkspaceClientProvider>
  );
}

export const Providers: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <HotkeysProvider>
      <QueryClientProvider client={queryClient}>
        <TRPCProvider trpcClient={trpcClient} queryClient={queryClient}>
          <HostTRPCProvider
            trpcClient={hostTrpcClient}
            queryClient={queryClient}
          >
            <ConnectedWorkspaceProvider>
              <ThemeWrapper>{children}</ThemeWrapper>
            </ConnectedWorkspaceProvider>
          </HostTRPCProvider>
        </TRPCProvider>
      </QueryClientProvider>
    </HotkeysProvider>
  );
};
