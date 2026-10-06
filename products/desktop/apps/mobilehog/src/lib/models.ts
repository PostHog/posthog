const BRANDS = new Set(["claude", "gemini", "anthropic", "openai"]);
const ACRONYMS = new Set(["gpt", "o"]);

// "claude-opus-5-5" reads as "Opus 5.5": no brand, version digits joined.
export function shortModelName(id: string): string {
  const parts = (id.split("/").pop() ?? id).split("-");
  // Keep the brand when it is the only name, as in "gemini-3-pro".
  const dropBrand = BRANDS.has(parts[0]) && /^[a-z]/.test(parts[1] ?? "");
  const words = parts
    .slice(dropBrand ? 1 : 0)
    .filter((part) => !/^\d{8}$/.test(part));
  const out: string[] = [];
  for (const word of words) {
    const previous = out[out.length - 1];
    if (/^\d+$/.test(word) && previous && /^\d+(\.\d+)*$/.test(previous)) {
      out[out.length - 1] = `${previous}.${word}`;
    } else if (ACRONYMS.has(word)) {
      out.push(word.toUpperCase());
    } else {
      out.push(word.charAt(0).toUpperCase() + word.slice(1));
    }
  }
  return out.join(" ");
}
