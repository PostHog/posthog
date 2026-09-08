import { create } from "zustand";

/**
 * The embedded browser is a NATIVE view that paints above the renderer, so
 * any renderer overlay that can overlap its rectangle (menus, popovers,
 * dialogs) must hide the view while open. This counter is that cooperation
 * point: acquire() on open, release() on close; the browser panel hides its
 * view while count > 0.
 */
interface EmbeddedBrowserObscuredState {
  count: number;
  acquire: () => void;
  release: () => void;
}

export const useEmbeddedBrowserObscuredStore =
  create<EmbeddedBrowserObscuredState>((set) => ({
    count: 0,
    acquire: () => set((state) => ({ count: state.count + 1 })),
    release: () => set((state) => ({ count: Math.max(0, state.count - 1) })),
  }));
