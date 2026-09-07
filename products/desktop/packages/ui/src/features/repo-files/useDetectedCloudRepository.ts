import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

export function useDetectedCloudRepository(
  folderPath: string | null | undefined,
): string | null {
  const trpc = useHostTRPC();
  const { data } = useQuery({
    ...trpc.git.detectRepo.queryOptions({ directoryPath: folderPath ?? "" }),
    enabled: !!folderPath,
    staleTime: 60_000,
  });

  if (!data?.organization || !data?.repository) return null;
  return `${data.organization}/${data.repository}`.toLowerCase();
}
