import { describe, expect, it } from "vitest";
import { moveRange } from "./sourceEdits";

const FILE = "src/canvas.tsx";
const SOURCE = `<main>
  <section>
    <p>A</p>
    <p>B</p>
  </section>
</main>`;

function range(snippet: string) {
  const start = SOURCE.indexOf(snippet);
  return { file: FILE, start, end: start + snippet.length };
}

describe("moveRange", () => {
  it("moves a child out to just after its parent", () => {
    const section = SOURCE.slice(
      SOURCE.indexOf("<section>"),
      SOURCE.indexOf("</section>") + "</section>".length,
    );
    const moved = moveRange({ [FILE]: SOURCE }, range("<p>B</p>"), {
      ...range(section),
      place: "after",
    });
    expect(moved[FILE]?.replace(/\n\s*\n/g, "\n")).toBe(`<main>
  <section>
    <p>A</p>
  </section>
  <p>B</p>
</main>`);
  });
});
