export function injectedReferenceKeys(text: string): string[] {
  const keys: string[] = [];
  let inBlock = false;
  for (const line of text.split("\n")) {
    if (line.includes("<posthog_reference_context")) inBlock = true;
    if (line.includes("</posthog_reference_context>")) inBlock = false;
    if (!inBlock || !line.startsWith("{")) continue;
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }
    const id = record.document_id || record.id;
    if (typeof record.kind === "string" && typeof id === "string" && id) {
      keys.push(`${record.kind}:${id}`);
    }
  }
  return keys;
}
