import {
  Circle,
  Eye,
  LockOpen,
  Pause,
  Pencil,
  Robot,
  ShieldCheck,
} from "@phosphor-icons/react";

export interface ModeStyle {
  icon: React.ReactNode;
  className: string;
}

export const MODE_STYLES: Record<string, ModeStyle> = {
  plan: {
    icon: <Pause size={12} weight="bold" />,
    className: "text-amber-11",
  },
  default: {
    icon: <Pencil size={12} />,
    className: "text-gray-11",
  },
  acceptEdits: {
    icon: <ShieldCheck size={12} weight="fill" />,
    className: "text-green-11",
  },
  bypassPermissions: {
    icon: <LockOpen size={12} weight="bold" />,
    className: "text-red-11",
  },
  auto: {
    icon: <Robot size={12} weight="fill" />,
    className: "text-blue-11",
  },
  "read-only": {
    icon: <Eye size={12} />,
    className: "text-amber-11",
  },
  "full-access": {
    icon: <LockOpen size={12} weight="bold" />,
    className: "text-red-11",
  },
};

export const DEFAULT_MODE_STYLE: ModeStyle = {
  icon: <Circle size={12} />,
  className: "text-gray-11",
};

export function getModeStyle(value: string): ModeStyle {
  return MODE_STYLES[value] ?? DEFAULT_MODE_STYLE;
}

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
