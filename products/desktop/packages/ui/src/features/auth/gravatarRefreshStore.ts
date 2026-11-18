import { create } from "zustand";

interface GravatarRefreshStore {
  refreshedAtByEmail: Record<string, number>;
  setRefreshedAt: (email: string, refreshedAt: number) => void;
}

export const useGravatarRefreshStore = create<GravatarRefreshStore>((set) => ({
  refreshedAtByEmail: {},
  setRefreshedAt: (email, refreshedAt) => {
    set((state) => ({
      refreshedAtByEmail: {
        ...state.refreshedAtByEmail,
        [email]: refreshedAt,
      },
    }));
  },
}));
