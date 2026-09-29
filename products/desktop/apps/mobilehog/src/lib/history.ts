import { create } from "zustand";

// Only drawer scenes take part in swipe back/forward. Sheets (settings,
// config, picker) and login live on the root stack and are excluded.
const DRAWER_PATH = /^\/(task\/|activity$|self-driving$|$)/;

interface NavHistoryState {
  back: string[];
  forward: string[];
  current: string | null;
  // Path just navigated to via goBack/goForward, so recording it does not
  // disturb the stacks.
  expected: string | null;
  record: (path: string) => void;
  goBack: () => string | null;
  goForward: () => string | null;
}

export const useNavHistory = create<NavHistoryState>((set, get) => ({
  back: [],
  forward: [],
  current: null,
  expected: null,

  record: (path) => {
    if (!DRAWER_PATH.test(path)) return;
    const { back, current, expected } = get();
    if (path === current) return;
    if (path === expected) {
      set({ current: path, expected: null });
      return;
    }
    // A pending chat re-keyed to its real task id replaces its history entry;
    // going back to the dead placeholder would show an orphaned session.
    const replacing = current?.startsWith("/task/new-");
    set({
      back: current && !replacing ? [...back, current] : back,
      forward: [],
      current: path,
      expected: null,
    });
  },

  goBack: () => {
    const { back, forward, current } = get();
    const target = back[back.length - 1];
    if (!target) return null;
    set({
      back: back.slice(0, -1),
      forward: current ? [...forward, current] : forward,
      current: target,
      expected: target,
    });
    return target;
  },

  goForward: () => {
    const { back, forward, current } = get();
    const target = forward[forward.length - 1];
    if (!target) return null;
    set({
      forward: forward.slice(0, -1),
      back: current ? [...back, current] : back,
      current: target,
      expected: target,
    });
    return target;
  },
}));
