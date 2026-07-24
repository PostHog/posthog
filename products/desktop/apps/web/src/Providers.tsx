import { HostTRPCProvider } from "@posthog/host-router/react";
import { ThemeWrapper } from "@posthog/ui/primitives/ThemeWrapper";
import { WorkspaceClientProvider } from "@posthog/workspace-client/provider";
import { QueryClientProvider } from "@tanstack/react-query";
import type React from "react";
import { HotkeysProvider } from "react-hotkeys-hook";
import { queryClient } from "./web-container";
import { hostTrpcClient } from "./web-trpc";

// Web transport wiring — the per-host counterpart of apps/code's Providers.tsx.
// @posthog/ui consumes the HOST router context (useHostTRPCClient), so web needs
// HostTRPCProvider over the in-process client. No electron TrpcRouter context.
//
// It also mounts WorkspaceClientProvider with connection={null}: several
// task-detail components (useTaskData, FileTreePanel, staging) call
// useWorkspaceTRPC() unconditionally, so the context must exist or they throw.
// There is no workspace-server on the web host, so the provider points at its
// UNAVAILABLE dead URL — those local-only calls reject as failed queries (and
// are gated on a repoPath that cloud tasks never have, so they don't fire).

export const Providers: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <HotkeysProvider>
      <QueryClientProvider client={queryClient}>
        <HostTRPCProvider trpcClient={hostTrpcClient} queryClient={queryClient}>
          <WorkspaceClientProvider connection={null} queryClient={queryClient}>
            <ThemeWrapper>{children}</ThemeWrapper>
          </WorkspaceClientProvider>
        </HostTRPCProvider>
      </QueryClientProvider>
    </HotkeysProvider>
  );
};
