export function colonOffsetToSeconds(offset: string): number | null {
  const parts = offset.split(":");
  if (parts.length < 2 || parts.length > 3) return null;
  if (parts.some((p) => !/^\d+$/.test(p))) return null;
  const nums = parts.map(Number);
  const [h, m, s] = parts.length === 3 ? nums : [0, nums[0], nums[1]];
  if (m >= 60 || s >= 60) return null;
  const total = h * 3600 + m * 60 + s;
  return Number.isSafeInteger(total) ? total : null;
}

export function colonOffsetFromSeconds(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  const hrs = Math.floor(mins / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return hrs > 0
    ? `${pad(hrs)}:${pad(mins % 60)}:${pad(secs)}`
    : `${pad(mins)}:${pad(secs)}`;
}
