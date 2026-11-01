import { useEffect, useState } from "react";
import type { TodayClient, TodayState } from "../today";

// The web app polls this often while a briefing is written, and gives up after about half an hour.
const POLL_MS = 10_000;
const MAX_POLLS = 190;

// Today's briefing, read each time it comes into view. A briefing still being written is read again until it is done.
export function useToday(
  client: TodayClient | undefined,
  showing: boolean,
): TodayState {
  const [state, setState] = useState<TodayState>({ kind: "loading" });
  useEffect(() => {
    if (!client || !showing) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    const load = async (): Promise<void> => {
      const next = await client.load();
      if (stopped) return;
      setState(next);
      const writing =
        next.kind === "ready" &&
        (next.briefing.status === "collecting" ||
          next.briefing.status === "writing");
      if (writing && polls++ < MAX_POLLS) timer = setTimeout(load, POLL_MS);
    };
    void load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [client, showing]);
  return state;
}
