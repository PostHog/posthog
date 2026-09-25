import { OfflineWorkspace } from "@posthog/core/offline/workspace";
import * as FileSystem from "expo-file-system/legacy";
import { Platform } from "react-native";
import { accountStorageKey, type Session } from "@/lib/auth";

const workspaces = new Map<string, OfflineWorkspace>();
let cleanup = Promise.resolve();
export const WEEK = 7 * 24 * 60 * 60 * 1000;

export function clearAccountStorage(session: Session): Promise<void> {
  const host = Array.from(session.host, (character) =>
    character.charCodeAt(0).toString(16),
  ).join("-");
  const matches = (name: string): boolean =>
    name.startsWith(`mobilehog_workspace_${host}_`) &&
    name.endsWith(`_${session.userId}`);
  const closing = [...workspaces]
    .filter(([scope]) => matches(scope))
    .map(([scope, workspace]) => {
      workspaces.delete(scope);
      return workspace.close();
    });
  const removing = cleanup.then(async () => {
    await Promise.all(closing);
    if (Platform.OS === "web") {
      for (const key of Object.keys(localStorage))
        if (matches(key.split("/")[0])) localStorage.removeItem(key);
    } else if (FileSystem.documentDirectory) {
      for (const name of await FileSystem.readDirectoryAsync(
        FileSystem.documentDirectory,
      )) {
        if (matches(name))
          await FileSystem.deleteAsync(
            `${FileSystem.documentDirectory}${name}`,
            {
              idempotent: true,
            },
          );
      }
    }
  });
  cleanup = removing.catch(() => {});
  return removing;
}

async function prune(
  directory: string,
  referenced = new Set<string>(),
): Promise<void> {
  if (!(await FileSystem.getInfoAsync(directory)).exists) return;
  const entries = await FileSystem.readDirectoryAsync(directory);
  for (const name of entries.filter(
    (name) => name.startsWith("draft-") && name.endsWith(".json"),
  )) {
    try {
      const saved = JSON.parse(
        await FileSystem.readAsStringAsync(`${directory}${name}`),
      );
      if (Date.now() - saved.savedAt <= WEEK)
        for (const photo of saved.value.photos)
          if (typeof photo.uri === "string") referenced.add(photo.uri);
    } catch {}
  }
  for (const name of entries) {
    const path = `${directory}${name}`;
    const info = await FileSystem.getInfoAsync(path);
    if (!info.exists) continue;
    if (info.isDirectory) await prune(`${path}/`, referenced);
    else if (
      !referenced.has(path) &&
      Date.now() - info.modificationTime * 1000 > WEEK
    )
      await FileSystem.deleteAsync(path, { idempotent: true });
  }
}

export function deviceWorkspace(): OfflineWorkspace {
  const scope = accountStorageKey("mobilehog_workspace");
  const existing = workspaces.get(scope);
  if (existing) return existing;
  const directory = `${FileSystem.documentDirectory}${scope}/`;
  const ready = cleanup.then(() =>
    Platform.OS === "web" ? undefined : prune(directory).catch(() => {}),
  );
  const file = (key: string): string =>
    `${directory}${encodeURIComponent(key)}.json`;
  const workspace = new OfflineWorkspace({
    read: async (key) => {
      await ready;
      if (Platform.OS === "web") return localStorage.getItem(`${scope}/${key}`);
      if (!(await FileSystem.getInfoAsync(file(key))).exists) return null;
      return FileSystem.readAsStringAsync(file(key));
    },
    write: async (key, value) => {
      await ready;
      if (Platform.OS === "web") {
        localStorage.setItem(`${scope}/${key}`, value);
        return;
      }
      await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
      await FileSystem.writeAsStringAsync(`${file(key)}.tmp`, value);
      await FileSystem.moveAsync({ from: `${file(key)}.tmp`, to: file(key) });
    },
    remove: async (key) => {
      await ready;
      if (Platform.OS === "web") localStorage.removeItem(`${scope}/${key}`);
      else await FileSystem.deleteAsync(file(key), { idempotent: true });
    },
  });
  workspaces.set(scope, workspace);
  return workspace;
}
