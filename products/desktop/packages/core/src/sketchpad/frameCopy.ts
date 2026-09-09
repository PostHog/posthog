import { SKETCHPAD_FIELD_MAX_ENTRIES } from "@posthog/shared";
export const SHARED_TEXT_FULL = `This text is full. It holds ${SKETCHPAD_FIELD_MAX_ENTRIES.toLocaleString("en-US")} characters. Delete some before you write more.`;
export const SHARED_FIELD_READ_ONLY_STATE =
  "This key holds shared text. Use useSharedText or useSharedList to change it.";

export const SKETCHPAD_FRAGMENT_ERROR_TITLE = "This fragment did not run";
export const SKETCHPAD_FRAGMENT_ERROR_HINT =
  "Select Edit code in the fragment menu to fix it.";
