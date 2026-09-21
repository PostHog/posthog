import { create } from "zustand";

interface GravatarRefreshStore {
  refreshedAtByEmail: Record<string, number>;
  refresh: (email: string) => void;
}

export const useGravatarRefreshStore = create<GravatarRefreshStore>((set) => ({
  refreshedAtByEmail: {},
  refresh: (email) => {
    const normalized = email.trim().toLowerCase();
    if (!normalized) return;
    set((state) => ({
      refreshedAtByEmail: {
        ...state.refreshedAtByEmail,
        [normalized]: Math.max(
          Date.now(),
          (state.refreshedAtByEmail[normalized] ?? 0) + 1,
        ),
      },
    }));
  },
}));
