export function createFragmentCompiler(
  compile: (source: string) => string,
  maxCharacters = 2 * 1024 * 1024,
): (source: string) => string {
  const cache = new Map<string, string>();
  let characters = 0;
  return (source) => {
    const cached = cache.get(source);
    if (cached !== undefined) {
      cache.delete(source);
      cache.set(source, cached);
      return cached;
    }
    const output = compile(source);
    const size = source.length + output.length;
    if (size > maxCharacters) return output;
    while (characters + size > maxCharacters) {
      const oldest = cache.entries().next().value;
      if (!oldest) break;
      cache.delete(oldest[0]);
      characters -= oldest[0].length + oldest[1].length;
    }
    cache.set(source, output);
    characters += size;
    return output;
  };
}
