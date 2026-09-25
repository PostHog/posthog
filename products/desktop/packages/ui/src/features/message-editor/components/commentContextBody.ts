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
  let inSnippet = false;
  for (const line of body.split("\n")) {
    if (line.startsWith("```")) {
      inSnippet = !inSnippet;
      continue;
    }
    if (inSnippet) {
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
