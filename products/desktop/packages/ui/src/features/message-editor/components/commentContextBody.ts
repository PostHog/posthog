export type CommentContextDetails = {
  fields: { key: string; value: string }[];
  quote: string | null;
  snippet: string | null;
};

const FIELD_PATTERN = /^- \*\*(.+?)\*\* (.*)$/;

export function parseCommentContextBody(body: string): CommentContextDetails {
  const fields: CommentContextDetails["fields"] = [];
  const quoteLines: string[] = [];
  const snippetLines: string[] = [];
  let fence: string | null = null;
  for (const line of body.split("\n")) {
    const opening: string | undefined =
      fence === null ? line.match(/^`{3,}/)?.[0] : undefined;
    if (opening) {
      fence = opening;
      continue;
    }
    if (fence !== null && line === fence) {
      fence = null;
      continue;
    }
    if (fence !== null) {
      snippetLines.push(line);
      continue;
    }
    if (line.startsWith("> ") || line === ">") {
      quoteLines.push(line.slice(2));
      continue;
    }
    const field = line.match(FIELD_PATTERN);
    if (field) fields.push({ key: field[1], value: field[2] });
  }
  return {
    fields,
    quote: quoteLines.length > 0 ? quoteLines.join("\n") : null,
    snippet: snippetLines.length > 0 ? snippetLines.join("\n") : null,
  };
}
