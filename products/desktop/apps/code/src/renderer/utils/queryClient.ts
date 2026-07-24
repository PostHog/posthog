import type { Task } from "@posthog/shared/domain-types";
import { focusManager, QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      refetchOnWindowFocus: true,
    },
  },
});

// Electron renderers stay visible when the BrowserWindow loses OS focus, so
// `document.visibilitychange` (TanStack's default signal) never fires on
// app-switch. Listen to window `focus`/`blur` as well so refetchOnWindowFocus
// actually triggers when the user returns from an external browser.
focusManager.setEventListener((handleFocus) => {
  if (typeof window === "undefined") return;

  const onFocus = () => handleFocus(true);
  const onBlur = () => handleFocus(false);
  const onVisibilityChange = () => handleFocus(!document.hidden);

  window.addEventListener("focus", onFocus);
  window.addEventListener("blur", onBlur);
  document.addEventListener("visibilitychange", onVisibilityChange);

  return () => {
    window.removeEventListener("focus", onFocus);
    window.removeEventListener("blur", onBlur);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
});

export function getCachedTask(taskId: string): Task | undefined {
  return queryClient
    .getQueriesData<Task[]>({ queryKey: ["tasks", "list"] })
    .flatMap(([, tasks]) => tasks ?? [])
    .find((t) => t.id === taskId);
}
