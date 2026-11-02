import { type Dispatch, type SetStateAction, useEffect, useRef } from "react";
import { track } from "../analytics";
import {
  back,
  forward,
  type History,
  noHistory,
  spotOf,
  visited,
} from "../history";
import type { LayoutState } from "../layout";

export interface HistoryNav {
  back: () => void;
  forward: () => void;
}

// The chats visited, as Ctrl+[ and Ctrl+] step through them: every change of the focused pane or of the chat it
// shows is a spot, whatever caused it.
export function useHistory({
  layout,
  setLayout,
}: {
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
}): HistoryNav {
  const history = useRef<History>(noHistory);
  // A step lands on the spot it went to, which is then current, so it is not noted as a new one.
  useEffect(() => {
    history.current = visited(history.current, spotOf(layout));
  }, [layout]);
  const step = (direction: "back" | "forward"): void =>
    setLayout((state) => {
      const stepped = (direction === "back" ? back : forward)(
        history.current,
        state,
      );
      if (!stepped) return state;
      track("history stepped", { direction });
      history.current = stepped.history;
      return stepped.layout;
    });
  return { back: () => step("back"), forward: () => step("forward") };
}
