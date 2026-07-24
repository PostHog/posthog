const SUPPORTED_EXT = /\.(?:ts|tsx|js|jsx|mjs|cjs|py|rb|go)$/i;
const MAX_CONTENT_BYTES = 1_000_000;

export function isEnrichmentEligible(
  filePath: string,
  content: string | null | undefined,
): boolean {
  const hasContent =
    typeof content === "string" &&
    content.length > 0 &&
    content.length <= MAX_CONTENT_BYTES;
  return hasContent && SUPPORTED_EXT.test(filePath);
}
