import { QueryClient } from "@tanstack/react-query";
import { sessionIdentity, useAuth } from "@/lib/auth";
import { resetClient } from "@/lib/client";
import { useComposer } from "@/lib/composer";
import { resetEngine } from "@/lib/engine";
import { resetMcpClient } from "@/lib/mcp/client";
import { useRepo } from "@/lib/repo";
import { useSeenReports } from "@/lib/reports";
import { useSessions } from "@/lib/session";

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
  });
}

let queryClient = createQueryClient();

useAuth.subscribe((state, previous) => {
  if (sessionIdentity(state) === sessionIdentity(previous)) return;
  queryClient.clear();
  queryClient = createQueryClient();
  useSessions.getState().reset();
  resetEngine();
  resetClient();
  resetMcpClient();
  useComposer.getState().reset();
  useRepo.setState({ repository: undefined });
  useSeenReports.setState({ seen: new Set(), hydrated: false });
});

export function getAccountQueryClient(): QueryClient {
  return queryClient;
}
