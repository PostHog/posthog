import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useEffect, useRef } from "react";

/**
 * A thread picked on the artifact itself is read in the comments surface, so
 * the pick has to bring that surface with it. The one protocol behind that:
 * whoever can show the comments takes the request, opens, and acknowledges,
 * which is what clears the flag. A request is taken once, by nonce, so a
 * surface that stays mounted across several picks reacts to each of them and
 * to none of them twice.
 *
 * Requests arrive both while the surface is mounted and just before it mounts,
 * because the click that asks for a thread is often the click that navigates
 * into the session. Both are honored: a request that nobody acknowledged is
 * still outstanding, whenever it was written.
 */
export function useCommentFocusRequest(
  taskId: string,
  openComments: () => void,
): void {
  const focus = useCommentNavigationStore((state) => state.focusByTask[taskId]);
  const acknowledge = useCommentNavigationStore(
    (state) => state.acknowledgeCommentsTabOpen,
  );
  const takenNonce = useRef<number | null>(null);
  const openRef = useRef(openComments);
  openRef.current = openComments;

  useEffect(() => {
    if (!focus?.openCommentsTab) return;
    if (focus.nonce === takenNonce.current) return;
    takenNonce.current = focus.nonce;
    openRef.current();
    acknowledge(taskId, focus.nonce);
  }, [acknowledge, focus, taskId]);
}
