export const STRIP_DROP_TYPE = "tab-strip";

export interface StripDropData {
  type: typeof STRIP_DROP_TYPE;
}

export function isStripDropData(data: unknown): data is StripDropData {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === STRIP_DROP_TYPE
  );
}
