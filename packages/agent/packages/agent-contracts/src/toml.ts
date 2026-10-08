const TOML_ESCAPES: Record<string, string> = {
  "\b": "\\b",
  "\t": "\\t",
  "\n": "\\n",
  "\f": "\\f",
  "\r": "\\r",
  '"': '\\"',
  "\\": "\\\\",
};

/** A TOML basic string, quoted, with every character TOML requires escaped. */
export function tomlBasicString(value: string): string {
  const escaped = value.replace(
    // biome-ignore lint/suspicious/noControlCharactersInRegex: TOML requires escaping control characters
    /[\u0000-\u001f"\\\u007f]/g,
    (ch) =>
      TOML_ESCAPES[ch] ??
      `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
  return `"${escaped}"`;
}
