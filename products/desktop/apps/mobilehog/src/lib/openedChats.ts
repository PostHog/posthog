import type { Task } from "@posthog/shared/domain-types";
import type { MMKV } from "react-native-mmkv";
import { useAuth } from "@/lib/auth";
import { accountStore } from "@/lib/cache";

const OPENED_LIMIT = 50;

function openedScope(): { store: MMKV; key: string } | null {
  const { session } = useAuth.getState();
  if (!session) return null;
  return {
    store: accountStore(session),
    key: `opened-${session.projectId}`,
  };
}

function readOpened(store: MMKV, key: string): string[] {
  try {
    const order = JSON.parse(store.getString(key) ?? "[]");
    return Array.isArray(order)
      ? order.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

export function recordOpened(taskId: string): void {
  const scope = openedScope();
  if (!scope) return;
  const order = [
    taskId,
    ...readOpened(scope.store, scope.key).filter((id) => id !== taskId),
  ];
  scope.store.set(scope.key, JSON.stringify(order.slice(0, OPENED_LIMIT)));
}

// Task ids opened on this device, most recent first.
export function loadOpened(): string[] {
  const scope = openedScope();
  return scope ? readOpened(scope.store, scope.key) : [];
}

// Opened ids whose task is gone (deleted or archived) are skipped, and recent
// tasks fill the rest so a fresh install still shows something.
export function lastOpened(
  opened: string[],
  recent: Task[],
  limit: number,
): Task[] {
  const byId = new Map(recent.map((task) => [task.id, task]));
  const picked = new Map<string, Task>();
  for (const task of [
    ...opened.flatMap((id) => byId.get(id) ?? []),
    ...recent,
  ]) {
    if (picked.size === limit) break;
    picked.set(task.id, task);
  }
  return [...picked.values()];
}
