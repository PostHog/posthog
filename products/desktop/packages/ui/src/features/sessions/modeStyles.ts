// Short, human labels keyed by mode id. The raw permission-option names are long
// "Yes, and ..." strings; these read cleanly on the Approve button and in the
// "Approve and…" dropdown. Callers fall back to the raw option name when a mode
// isn't listed here.
export const MODE_LABELS: Record<string, string> = {
  plan: "Plan",
  default: "Manually approve edits",
  acceptEdits: "Accept edits",
  auto: "Auto",
  bypassPermissions: "Bypass permissions",
  "read-only": "Read-only",
  "full-access": "Full access",
};
