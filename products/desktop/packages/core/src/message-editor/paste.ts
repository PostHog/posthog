const URL_ONLY_REGEX = /^https?:\/\/\S+$/;

export function isUrlOnly(text: string): boolean {
  return URL_ONLY_REGEX.test(text);
}

export function buildMarkdownLink(selectedText: string, url: string): string {
  return `[${selectedText}](${url})`;
}

export function isBashModeText(text: string): boolean {
  return text.trimStart().startsWith("!");
}

export function extractBashCommand(text: string): string {
  return text.slice(1).trim();
}

export function shouldAutoConvertLongText(
  text: string,
  threshold: string,
): boolean {
  return threshold !== "off" && text.length > Number(threshold);
}

export function buildPastedTextLabel(
  pasteNumber: number,
  lineCount: number,
): string {
  return `Pasted text #${pasteNumber} (${lineCount} lines)`;
}

export interface AutoConvertedPaste {
  clipboardText: string;
  insertText: string;
  chipId: string;
}

export function isRepeatOfAutoConvertedPaste(
  last: AutoConvertedPaste | null,
  clipboardText: string | null | undefined,
): last is AutoConvertedPaste {
  return (
    last !== null && !!clipboardText && clipboardText === last.clipboardText
  );
}
