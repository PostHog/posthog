/**
 * The host-side view id for a browser tab. Derived (not stored) so cleanup
 * paths that only see the panel tree — tab close, close-others, task archive —
 * can address the native view without extra bookkeeping.
 */
export function browserViewId(taskId: string, tabId: string): string {
  return `task-browser:${taskId}:${tabId}`;
}
