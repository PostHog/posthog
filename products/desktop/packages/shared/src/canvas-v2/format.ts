import type { CanvasV2Fragment, CanvasV2Snapshot } from "./schemas";

export function firstCodeLine(code: string): string {
  const line = code.split("\n").find((l) => l.trim().length > 0) ?? "";
  const trimmed = line.trim();
  return trimmed.length > 100 ? `${trimmed.slice(0, 97)}...` : trimmed;
}

export function formatFragmentLine(fragment: CanvasV2Fragment): string {
  const title = fragment.title ?? "(no title)";
  const size = `${Math.round(fragment.w)}×${Math.round(fragment.h)}`;
  const position = `${Math.round(fragment.x)},${Math.round(fragment.y)}`;
  return `${fragment.id} · ${title} · ${position} · ${size} · ${firstCodeLine(fragment.code)}`;
}

export function formatBoardForAgent(
  snapshot: CanvasV2Snapshot,
  headSeq: number,
): string {
  const lines: string[] = [];
  const fragments = [...snapshot.fragments].sort(
    (a, b) => a.y - b.y || a.x - b.x,
  );
  lines.push(`Fragments (${fragments.length}):`);
  if (fragments.length === 0) {
    lines.push("  (none)");
  }
  for (const fragment of fragments) {
    lines.push(`  ${formatFragmentLine(fragment)}`);
  }
  const keys = Object.keys(snapshot.state).sort();
  lines.push(`State keys (${keys.length}):`);
  if (keys.length === 0) {
    lines.push("  (none)");
  }
  for (const key of keys) {
    lines.push(`  ${key} = ${previewJson(snapshot.state[key])}`);
  }
  lines.push(`headSeq: ${headSeq}`);
  return lines.join("\n");
}

function previewJson(value: unknown): string {
  let text: string;
  try {
    text = JSON.stringify(value) ?? "undefined";
  } catch {
    text = "(unserializable)";
  }
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}
