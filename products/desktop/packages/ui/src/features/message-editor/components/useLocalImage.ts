import { isClipboardAttachmentPath } from "@posthog/shared";
import { readFileAsDataUrl } from "@posthog/ui/features/message-editor/hostApi";
import { useQuery } from "@tanstack/react-query";

export function useLocalImage(filePath: string | undefined): string | null {
  const readable = !!filePath && isClipboardAttachmentPath(filePath);
  const query = useQuery({
    queryKey: ["os", "readFileAsDataUrl", filePath ?? ""],
    queryFn: () => readFileAsDataUrl({ filePath: filePath ?? "" }),
    enabled: readable,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  return readable ? (query.data ?? null) : null;
}
