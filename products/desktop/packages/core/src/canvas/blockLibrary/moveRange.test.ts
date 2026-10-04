import { describe, expect, it } from "vitest";
import { moveRange, shrinkGrid } from "./sourceEdits";

const FILE = "src/canvas.tsx";
const SOURCE = `<main>
  <section>
    <p>A</p>
    <p>B</p>
  </section>
</main>`;

function range(snippet: string, source = SOURCE) {
  const start = source.indexOf(snippet);
  return { file: FILE, start, end: start + snippet.length };
}

function element(open: string, close: string, source: string) {
  const start = source.indexOf(open);
  const end = source.indexOf(close, start) + close.length;
  return { file: FILE, start, end };
}

const ROW = `<main>
  <div className="grid gap-4 md:grid-cols-3">
    <Card>A</Card>
    <Card>B</Card>
    <Card>C</Card>
  </div>
  <Card>D</Card>
</main>`;

const PAIR = `<main>
  <div className="grid gap-4 md:grid-cols-2">
    <Card>A</Card>
    <Card>B</Card>
  </div>
  <Card>D</Card>
</main>`;

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

  it.each([
    {
      name: "moving a card out of a row drops a column",
      target: { ...range("<Card>D</Card>", ROW), place: "after" as const },
      columns: "md:grid-cols-2",
    },
    {
      name: "reordering inside the row keeps the columns",
      target: { ...range("<Card>A</Card>", ROW), place: "before" as const },
      columns: "md:grid-cols-3",
    },
  ])("$name", ({ target, columns }) => {
    const grid = element("<div", "</div>", ROW);
    const moved = moveRange(
      { [FILE]: ROW },
      range("<Card>C</Card>", ROW),
      target,
      grid,
    );
    expect(moved[FILE]).toContain(`className="grid gap-4 ${columns}"`);
  });

  it("moving a card into a full row adds a column", () => {
    const grid = element("<div", "</div>", PAIR);
    const moved = moveRange({ [FILE]: PAIR }, range("<Card>D</Card>", PAIR), {
      ...range("<Card>B</Card>", PAIR),
      place: "after",
      grow: { ...grid, columns: 2 },
    });
    expect(moved[FILE]).toBe(`<main>
  <div className="grid gap-4 md:grid-cols-3">
    <Card>A</Card>
    <Card>B</Card>
    <Card>D</Card>
  </div>
</main>`);
  });
});

describe("shrinkGrid", () => {
  it.each([
    {
      children: "<Card>A</Card><Card>B</Card><Card>C</Card>",
      className: "grid sm:grid-cols-2 lg:grid-cols-3",
      expected: "grid sm:grid-cols-2 lg:grid-cols-2",
    },
    {
      children: '<Card>A</Card><Card title="B" />',
      className: "grid md:grid-cols-3",
      expected: "grid md:grid-cols-1",
    },
    {
      children: "<Card>A</Card><Card>B</Card><Card>C</Card><Card>D</Card>",
      className: "grid grid-cols-2",
      expected: "grid grid-cols-2",
    },
    {
      children: "<Card>A</Card><Card>B</Card><Card>C</Card>",
      className: "grid grid-cols-12",
      expected: "grid grid-cols-12",
    },
    {
      children: "<Card>A</Card><Card>B</Card>{show && <Card>C</Card>}",
      className: "grid grid-cols-3",
      expected: "grid grid-cols-3",
    },
  ])(
    "$className around $children becomes $expected",
    ({ children, className, expected }) => {
      const source = `<div className="${className}">${children}</div>`;
      const grid = { file: FILE, start: 0, end: source.length };
      const shrunk = shrinkGrid(
        { [FILE]: source },
        grid,
        range("<Card>A</Card>", source),
      );
      expect(shrunk[FILE]).toBe(
        `<div className="${expected}">${children}</div>`,
      );
    },
  );

  it("leaves the grid alone when the removed card sits outside it", () => {
    const grid = element("<div", "</div>", ROW);
    const files = { [FILE]: ROW };
    expect(shrinkGrid(files, grid, range("<Card>D</Card>", ROW))).toBe(files);
  });
});
