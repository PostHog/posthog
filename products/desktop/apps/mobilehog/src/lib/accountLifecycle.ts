import { QueryClient } from "@tanstack/react-query";
import { sessionIdentity, useAuth } from "@/lib/auth";
import {
  CACHE_MAX_AGE,
  clearAccountCache,
  persistQueryCache,
} from "@/lib/cache";
import { resetClient } from "@/lib/client";
import { useComposer } from "@/lib/composer";
import { resetEngine } from "@/lib/engine";
import { resetMcpClient } from "@/lib/mcp/client";
import { useRepo } from "@/lib/repo";
import { resetUnstartedReportTasks, useSeenReports } from "@/lib/reports";
import { useSessions } from "@/lib/session";

let stopPersisting: (() => void) | undefined;

function createQueryClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      // Saved queries must outlive their screens to stay readable offline.
      queries: { retry: 1, refetchOnWindowFocus: false, gcTime: CACHE_MAX_AGE },
    },
  });
  stopPersisting?.();
  const { session } = useAuth.getState();
  stopPersisting = session ? persistQueryCache(client, session) : undefined;
  return client;
}

let queryClient = createQueryClient();

useAuth.subscribe((state, previous) => {
  if (sessionIdentity(state) === sessionIdentity(previous)) return;
  if (previous.session && !state.session) clearAccountCache(previous.session);
  queryClient.clear();
  queryClient = createQueryClient();
  useSessions.getState().reset();
  resetEngine();
  resetClient();
  resetMcpClient();
  useComposer.getState().reset();
  useRepo.setState({ repository: undefined });
  useSeenReports.setState({ seen: new Set(), hydrated: false });
  resetUnstartedReportTasks();
});

export function getAccountQueryClient(): QueryClient {
  return queryClient;
}
