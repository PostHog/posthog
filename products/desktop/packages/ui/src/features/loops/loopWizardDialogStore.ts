import { create } from "zustand";
import { useLoopDraftStore } from "./loopDraftStore";
import type { LoopContextTargetDraft } from "./loopFormTypes";
import type { LoopTemplate } from "./loopTemplates";

interface LoopWizardDialogState {
  open: boolean;
  spaceName: string | null;
  show: (spaceName: string | null) => void;
  close: () => void;
}

export const useLoopWizardDialogStore = create<LoopWizardDialogState>()(
  (set) => ({
    open: false,
    spaceName: null,
    show: (spaceName) => set({ open: true, spaceName }),
    close: () => set({ open: false, spaceName: null }),
  }),
);

export function openNewLoop(): void {
  const spaceName =
    useLoopDraftStore.getState().prefill?.contextTarget?.name ?? null;
  useLoopWizardDialogStore.getState().show(spaceName);
}

export function startNewLoop(options?: {
  template?: LoopTemplate;
  context?: LoopContextTargetDraft;
}): void {
  const { template, context } = options ?? {};
  useLoopDraftStore.getState().setPrefill(
    template || context
      ? {
          ...(template
            ? { description: template.description, ...template.build() }
            : {}),
          ...(context ? { contextTarget: context } : {}),
        }
      : null,
  );
  openNewLoop();
}
