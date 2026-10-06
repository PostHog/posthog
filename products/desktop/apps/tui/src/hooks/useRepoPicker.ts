import { useEffect, useRef, useState } from "react";
import { messageOf } from "../errors";
import { applyPickerKey, openPicker, type Picker, pickerKey } from "../picker";
import { loadPrefs, savePrefs } from "../prefs";
import type { FlashNotice } from "./useNotice";

const SEARCH_PAUSE_MS = 250;

export interface RepoPicker {
  // The repositories the pane's next cloud chat starts with.
  reposFor: (paneId: string) => string[];
  // The pane's open /repo picker, if any.
  pickerFor: (paneId: string) => Picker | undefined;
  open: (paneId: string) => void;
  // Takes a key for the pane's open picker; false when the pane has none.
  onKey: (paneId: string, sequence: string) => boolean;
}

// /repo: each pane keeps its own repositories for new cloud chats, saved between runs.
// A pane that never picked starts with the repository of the folder the TUI started in.
export function useRepoPicker({
  search,
  defaultRepo,
  flashNotice,
}: {
  // Null while signed out.
  search: ((query: string) => Promise<string[]>) | null;
  defaultRepo: string | null;
  flashNotice: FlashNotice;
}): RepoPicker {
  const [repos, setRepos] = useState<Record<string, string[]>>(
    () => loadPrefs().paneRepositories,
  );
  const [pickers, setPickers] = useState<Map<string, Picker>>(new Map());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  // The latest search per pane, so an older answer arriving late is dropped.
  const latest = useRef(new Map<string, number>());

  useEffect(
    () => () => {
      for (const timer of timers.current.values()) clearTimeout(timer);
    },
    [],
  );

  const update = (paneId: string, change: (picker: Picker) => Picker): void =>
    setPickers((current) => {
      const picker = current.get(paneId);
      return picker ? new Map(current).set(paneId, change(picker)) : current;
    });

  const close = (paneId: string): void => {
    clearTimeout(timers.current.get(paneId));
    setPickers((current) => {
      const next = new Map(current);
      next.delete(paneId);
      return next;
    });
  };

  const searchFor = (paneId: string, query: string): void => {
    clearTimeout(timers.current.get(paneId));
    if (!search) return;
    const id = (latest.current.get(paneId) ?? 0) + 1;
    latest.current.set(paneId, id);
    timers.current.set(
      paneId,
      setTimeout(() => {
        search(query).then(
          (results) => {
            if (latest.current.get(paneId) !== id) return;
            update(paneId, (picker) => ({
              ...picker,
              results,
              loading: false,
              error: undefined,
            }));
          },
          (error: unknown) => {
            if (latest.current.get(paneId) !== id) return;
            update(paneId, (picker) => ({
              ...picker,
              loading: false,
              error: `Couldn't search repositories: ${messageOf(error)}`,
            }));
          },
        );
      }, SEARCH_PAUSE_MS),
    );
  };

  const reposFor = (paneId: string): string[] =>
    repos[paneId] ?? (defaultRepo ? [defaultRepo] : []);

  return {
    reposFor,
    pickerFor: (paneId) => pickers.get(paneId),
    open: (paneId) => {
      if (!search) {
        flashNotice("Sign in to pick repositories: type /login", { paneId });
        return;
      }
      setPickers((current) =>
        new Map(current).set(
          paneId,
          openPicker(
            "Repositories",
            reposFor(paneId),
            "New cloud chats in this pane clone these",
          ),
        ),
      );
      searchFor(paneId, "");
    },
    onKey: (paneId, sequence) => {
      const picker = pickers.get(paneId);
      if (!picker) return false;
      const key = pickerKey(sequence);
      if (!key) return true;
      const next = applyPickerKey(picker, key);
      if (next === "dismiss") {
        close(paneId);
        return true;
      }
      if (next === "confirm") {
        close(paneId);
        const chosen = picker.selected;
        const saved = { ...repos, [paneId]: chosen };
        setRepos(saved);
        savePrefs({ paneRepositories: saved });
        flashNotice(
          chosen.length > 0
            ? `New cloud chats here clone ${chosen.join(", ")}`
            : "New cloud chats here start without a repository",
          { paneId },
        );
        return true;
      }
      update(paneId, () => ({
        ...next,
        loading: next.query !== picker.query ? true : next.loading,
      }));
      if (next.query !== picker.query) searchFor(paneId, next.query);
      return true;
    },
  };
}
