// Default name for a canvas created without one. Also the marker used to
// detect a still-unnamed canvas worth auto-naming from its generation prompt.
export const UNTITLED_CANVAS_NAME = "Untitled canvas";

// True when a canvas name is a placeholder (never user-chosen), so auto-naming
// from a generation prompt is safe and won't clobber a real title.
export function isPlaceholderCanvasName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed === UNTITLED_CANVAS_NAME || trimmed === "Untitled dashboard";
}
