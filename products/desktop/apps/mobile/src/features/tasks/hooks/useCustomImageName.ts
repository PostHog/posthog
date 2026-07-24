import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/features/auth";
import { getSandboxCustomImages, getSandboxEnvironments } from "../api";

export const sandboxKeys = {
  customImages: () => ["sandbox-custom-images"] as const,
  environments: () => ["sandbox-environments"] as const,
};

interface UseCustomImageNameArgs {
  customImageId: string | null;
  sandboxEnvironmentId: string | null;
  enabled: boolean;
}

// Returns null while loading, when the fetch fails (custom images disabled), or
// when the image can't be resolved — in every case the badge renders nothing.
export function useCustomImageName({
  customImageId,
  sandboxEnvironmentId,
  enabled,
}: UseCustomImageNameArgs): string | null {
  const { projectId, oauthAccessToken } = useAuthStore();
  const canQuery = enabled && !!projectId && !!oauthAccessToken;
  const hasImageRef = !!customImageId || !!sandboxEnvironmentId;

  const imagesQuery = useQuery({
    queryKey: sandboxKeys.customImages(),
    queryFn: getSandboxCustomImages,
    enabled: canQuery && hasImageRef,
    staleTime: 60_000,
    retry: 0,
  });

  const environmentsQuery = useQuery({
    queryKey: sandboxKeys.environments(),
    queryFn: getSandboxEnvironments,
    enabled: canQuery && !!sandboxEnvironmentId,
    staleTime: 60_000,
    retry: 0,
  });

  const environment = sandboxEnvironmentId
    ? environmentsQuery.data?.find((env) => env.id === sandboxEnvironmentId)
    : undefined;

  const imageId = customImageId ?? environment?.custom_image_id ?? null;
  if (!imageId) return null;

  return (
    imagesQuery.data?.find((image) => image.id === imageId)?.name ??
    environment?.custom_image_name ??
    null
  );
}
