interface DevFlagsShape {
  devMode: boolean;
}

function readBootFlags(): DevFlagsShape {
  if (typeof window === "undefined") return { devMode: false };
  const raw = window.__posthogDevFlags;
  if (!raw || typeof raw !== "object") return { devMode: false };
  return { devMode: raw.devMode === true };
}

export const BOOT_DEV_FLAGS: DevFlagsShape = readBootFlags();

export function isDevModeAtBoot(): boolean {
  return BOOT_DEV_FLAGS.devMode;
}
