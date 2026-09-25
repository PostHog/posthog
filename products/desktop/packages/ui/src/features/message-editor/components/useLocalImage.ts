import { readFileAsDataUrl } from "@posthog/ui/features/message-editor/hostApi";
import { useQuery } from "@tanstack/react-query";

export function useLocalImage(filePath: string | undefined): string | null {
  const query = useQuery({
    queryKey: ["os", "readFileAsDataUrl", filePath ?? ""],
    queryFn: () => readFileAsDataUrl({ filePath: filePath ?? "" }),
    enabled: !!filePath,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  return query.data ?? null;
}
