import { Platform } from "react-native";

/**
 * iPhone renders `modal` as a full-screen sheet; iPad renders it as an inset
 * page-sheet card, which breaks the phone-tuned keyboard math (screen-relative
 * keyboard heights double-count against a sheet UIKit is already resizing) and
 * floats task screens in a small card. Present modals full-screen on iPad.
 */
export const MODAL_PRESENTATION =
  Platform.OS === "ios" && Platform.isPad
    ? ("fullScreenModal" as const)
    : ("modal" as const);

/**
 * Top offset for floating chrome inside modal-presented screens. iPhone
 * sheets already sit below the status bar, so a fixed 6pt breathing space
 * suffices; full-screen modals (iPad, Android) extend under the status bar
 * and need the real safe-area inset.
 */
export function modalTopOffset(safeAreaTop: number): number {
  return MODAL_PRESENTATION === "modal" && Platform.OS === "ios"
    ? 6
    : safeAreaTop;
}
