import { getDefaultReviewMode } from "@posthog/ui/features/code-review/getDefaultReviewMode";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { taskSearchDelay } from "@posthog/ui/features/command/taskSearchQuery";
import { useTaskSearch } from "@posthog/ui/features/command/useTaskSearch";
import { useCallback, useEffect, useRef, useState } from "react";

export function useRemoteTaskSearch(open: boolean, query: string) {
  const [remoteQuery, setRemoteQuery] = useState("");
  const remoteSearchAllowedRef = useRef(true);

  useEffect(() => {
    const trimmed = query.trim();
    const delay = taskSearchDelay(trimmed);
    if (!open || delay === null) {
      setRemoteQuery("");
      return;
    }
    const timer = window.setTimeout(
      () => setRemoteQuery(remoteSearchAllowedRef.current ? trimmed : ""),
      delay,
    );
    return () => window.clearTimeout(timer);
  }, [open, query]);

  const { data: searchResults = [] } = useTaskSearch(remoteQuery, open);
  return { remoteQuery, remoteSearchAllowedRef, searchResults };
}

export function useSystemPrefersDark(): boolean {
  const [systemPrefersDark, setSystemPrefersDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) =>
      setSystemPrefersDark(event.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  return systemPrefersDark;
}

export function useOpenReviewPanel(taskId?: string): () => void {
  const setReviewMode = useReviewNavigationStore(
    (state) => state.setReviewMode,
  );
  const getReviewMode = useReviewNavigationStore(
    (state) => state.getReviewMode,
  );

  return useCallback(() => {
    if (!taskId) return;
    if (getReviewMode(taskId) === "closed") {
      setReviewMode(taskId, getDefaultReviewMode());
    }
  }, [getReviewMode, setReviewMode, taskId]);
}
