import { create } from "zustand";

export interface ObjectSheetTarget {
  kind: string;
  id: string;
  name: string;
}

interface ObjectSheetStore {
  /** A sheet host is mounted, so a reference outside a session opens here instead of the browser. */
  sheetEnabled: boolean;
  /** Library can load the web app, so "open full" stays in the app. */
  libraryAvailable: boolean;
  object: ObjectSheetTarget | null;
  setAvailability: (availability: {
    sheetEnabled: boolean;
    libraryAvailable: boolean;
  }) => void;
  openObject: (object: ObjectSheetTarget) => void;
  closeObject: () => void;
}

export const useObjectSheetStore = create<ObjectSheetStore>()((set) => ({
  sheetEnabled: false,
  libraryAvailable: false,
  object: null,
  setAvailability: (availability) => set(availability),
  openObject: (object) => set({ object }),
  closeObject: () => set({ object: null }),
}));
