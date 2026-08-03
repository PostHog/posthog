// A canvas-generation task's initial prompt carries the standing authoring
// contract + publishing/data rules wrapped in a
// `<canvas_generation_instructions> ... </canvas_generation_instructions>`
// element (see buildFreeformGenerationPrompt). The conversation UI collapses
// that element into a single clickable tag instead of rendering the whole body
// inline, so these helpers detect and pull it out of the stored message text.
//
// The body shown is exactly what was sent in the prompt — parsed from the stored
// event, never regenerated.
const CANVAS_INSTRUCTIONS_REGEX =
  /<canvas_generation_instructions\b[^>]*>([\s\S]*?)<\/canvas_generation_instructions>/;

export function hasCanvasInstructions(content: string): boolean {
  return CANVAS_INSTRUCTIONS_REGEX.test(content);
}

// Returns the canvas-instructions body plus the message text with the element
// removed (so the user's own request renders cleanly), or null when the content
// has no canvas-instructions element.
export function extractCanvasInstructions(content: string): {
  body: string;
  stripped: string;
} | null {
  const match = CANVAS_INSTRUCTIONS_REGEX.exec(content);
  if (match?.index === undefined) return null;

  const body = match[1].trim();
  const stripped = (
    content.slice(0, match.index) + content.slice(match.index + match[0].length)
  ).trim();

  return { body, stripped };
}
