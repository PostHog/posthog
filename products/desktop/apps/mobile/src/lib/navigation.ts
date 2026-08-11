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
