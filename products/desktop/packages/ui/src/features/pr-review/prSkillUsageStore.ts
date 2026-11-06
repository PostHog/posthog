import { create } from "zustand";
import { persist } from "zustand/middleware";

interface PrSkillUsageState {
  countsByScope: Record<string, Record<string, number>>;
  recordChoice: (scope: string, name: string) => void;
}

export const usePrSkillUsageStore = create<PrSkillUsageState>()(
  persist(
    (set) => ({
      countsByScope: {},
      recordChoice: (scope, name) =>
        set((state) => ({
          countsByScope: {
            ...state.countsByScope,
            [scope]: {
              ...state.countsByScope[scope],
              [name]: (state.countsByScope[scope]?.[name] ?? 0) + 1,
            },
          },
        })),
    }),
    {
      name: "pr-skill-usage",
      partialize: (state) => ({ countsByScope: state.countsByScope }),
    },
  ),
);
