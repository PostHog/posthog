import type { Task } from "@posthog/shared";
import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import { messageOf } from "../errors";
import { type LayoutState, openTask } from "../layout";
import { editQuery, type SearchRow, searchRows } from "../search";
import { sheetKey } from "../sheet";
import type { LocalChatState } from "../sidebar";
import type { WorkList } from "../work";

// Long enough that a typed word sends one request, not one per letter.
const DEBOUNCE_MS = 200;

export interface SearchState {
  open: boolean;
  query: string;
  // Null while the answer for this query is on its way.
  rows: SearchRow[] | null;
  error: string | null;
  index: number;
  toggle: () => void;
  // Raw key sequences while the search is open: typing, the cursor, and Enter.
  onKey: (sequence: string) => void;
}

// The full-screen task search: an empty query lists recent work, and a typed one asks the server.
export function useSearch({
  work,
  recent,
  setLayout,
  working,
  waiting,
  local,
}: {
  work: WorkList | undefined;
  recent: Task[] | null;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  working: Set<string>;
  waiting: Set<string>;
  local: LocalChatState;
}): SearchState {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const [found, setFound] = useState<{
    term: string;
    tasks: Task[];
    error: string | null;
  } | null>(null);
  const term = query.trim();

  useEffect(() => {
    if (!open || !work || !term) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      work.search(term).then(
        (tasks) => !cancelled && setFound({ term, tasks, error: null }),
        (error: unknown) =>
          !cancelled && setFound({ term, tasks: [], error: messageOf(error) }),
      );
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, work, term]);

  const answer = found?.term === term ? found : null;
  const tasks = !term || !work ? (recent ?? []) : (answer?.tasks ?? null);
  const rows = tasks && searchRows(tasks, { working, waiting, local });

  return {
    open,
    query,
    rows,
    error: term ? (answer?.error ?? null) : null,
    index,
    toggle: () => {
      setOpen((current) => !current);
      setQuery("");
      setIndex(0);
    },
    onKey: (sequence) => {
      const key = sheetKey(sequence);
      if (key?.kind === "up" || key?.kind === "down") {
        const step = key.kind === "down" ? 1 : -1;
        const last = Math.max(0, (rows?.length ?? 1) - 1);
        setIndex((current) => Math.max(0, Math.min(last, current + step)));
        return;
      }
      if (key?.kind === "choose") {
        const row = rows?.[index];
        if (!row) return;
        setLayout((current) => openTask(current, row.taskId, row.title));
        setOpen(false);
        return;
      }
      setQuery((current) => editQuery(current, sequence));
      setIndex(0);
    },
  };
}
