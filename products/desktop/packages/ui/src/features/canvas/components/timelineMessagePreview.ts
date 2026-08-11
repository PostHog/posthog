const TIMELINE_MESSAGE_PREVIEW_LENGTH = 100;

export function timelineMessagePreview(content: string): string {
  const characters = Array.from(content);
  if (characters.length <= TIMELINE_MESSAGE_PREVIEW_LENGTH) return content;
  return `${characters.slice(0, TIMELINE_MESSAGE_PREVIEW_LENGTH).join("")}…`;
}
