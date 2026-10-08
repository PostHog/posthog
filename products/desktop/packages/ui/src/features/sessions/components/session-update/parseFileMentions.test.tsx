import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseFileMentions } from "./parseFileMentions";

describe("parseFileMentions", () => {
  it.each([
    [
      "between words",
      'Look at <file path="src/a.ts" /> now',
      "Look at src/a.ts now",
    ],
    ["at the start", '<file path="src/a.ts" /> is wrong', "src/a.ts is wrong"],
    ["at the end", 'Open <file path="src/a.ts" />', "Open src/a.ts"],
    ["without spaces", 'See (<file path="src/a.ts" />)', "See (src/a.ts)"],
    [
      "between two mentions",
      '<file path="src/a.ts" /> <file path="src/b.ts" />',
      "src/a.ts src/b.ts",
    ],
    [
      "after a slash command",
      '/review <file path="src/a.ts" /> please',
      "/review src/a.ts please",
    ],
  ])("keeps the spacing around a mention %s", (_case, content, text) => {
    const { container } = render(<div>{parseFileMentions(content)}</div>);
    expect(container.textContent).toBe(text);
  });
});
