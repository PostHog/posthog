import { describe, expect, it } from "vitest";
import {
  layoutWorkSections,
  resizeWorkSections,
  type WorkSectionInput,
} from "./workSectionLayout";

function sections(
  pinned: [boolean, number],
  recent: [boolean, number],
  spaces: [boolean, number],
): WorkSectionInput[] {
  return [
    { id: "pinned", open: pinned[0], contentHeight: pinned[1] },
    { id: "recent", open: recent[0], contentHeight: recent[1] },
    { id: "spaces", open: spaces[0], contentHeight: spaces[1] },
  ];
}

describe("layoutWorkSections", () => {
  it.each([
    {
      name: "recent fills what pinned and spaces leave",
      input: sections([true, 90], [true, 1400], [true, 290]),
      expected: { pinned: 90, recent: 270, spaces: 240 },
    },
    {
      name: "spaces fills when recent is folded",
      input: sections([true, 90], [false, 1400], [true, 900]),
      expected: { pinned: 90, recent: 0, spaces: 510 },
    },
    {
      name: "pinned keeps its own height when it is the only open section",
      input: sections([true, 90], [false, 1400], [false, 290]),
      expected: { pinned: 90, recent: 0, spaces: 0 },
    },
    {
      name: "a short recent still fills the column",
      input: sections([true, 90], [true, 120], [true, 150]),
      expected: { pinned: 90, recent: 360, spaces: 150 },
    },
    {
      name: "a short recent fills the column when spaces is folded",
      input: sections([true, 90], [true, 120], [false, 290]),
      expected: { pinned: 90, recent: 510, spaces: 0 },
    },
    {
      name: "spaces keeps its own height when recent is folded",
      input: sections([true, 90], [false, 1400], [true, 150]),
      expected: { pinned: 90, recent: 0, spaces: 150 },
    },
    {
      name: "nothing is open",
      input: sections([false, 90], [false, 1400], [false, 290]),
      expected: { pinned: 0, recent: 0, spaces: 0 },
    },
  ])("$name", ({ input, expected }) => {
    expect(layoutWorkSections(input, 600)).toEqual(expected);
  });

  it("keeps a height the user dragged to", () => {
    const input = sections([true, 400], [true, 1400], [true, 290]);

    expect(layoutWorkSections(input, 600, { pinned: 300 })).toEqual({
      pinned: 300,
      recent: 60,
      spaces: 240,
    });
  });

  it("shrinks the other sections so the filling one keeps a usable height", () => {
    const input = sections([true, 400], [true, 1400], [true, 400]);

    const heights = layoutWorkSections(input, 200, {
      pinned: 150,
      spaces: 150,
    });

    expect(heights.recent).toBeGreaterThanOrEqual(56);
    expect(
      heights.pinned + heights.recent + heights.spaces,
    ).toBeLessThanOrEqual(200);
  });
});

describe("resizeWorkSections", () => {
  const input = sections([true, 300], [true, 1400], [true, 290]);
  const heights = layoutWorkSections(input, 600);

  it.each([
    {
      name: "drags the line under pinned down",
      upper: "pinned" as const,
      lower: "recent" as const,
      delta: 50,
      expected: { pinned: heights.pinned + 50 },
    },
    {
      name: "stops pinned at the height of its items",
      upper: "pinned" as const,
      lower: "recent" as const,
      delta: 500,
      expected: { pinned: 300 },
    },
    {
      name: "drags the line above spaces up",
      upper: "recent" as const,
      lower: "spaces" as const,
      delta: -30,
      expected: { spaces: heights.spaces + 30 },
    },
    {
      name: "stops spaces at the smallest height a drag allows",
      upper: "recent" as const,
      lower: "spaces" as const,
      delta: 500,
      expected: { spaces: 40 },
    },
  ])("$name", ({ upper, lower, delta, expected }) => {
    expect(
      resizeWorkSections({
        sections: input,
        heights,
        upper,
        lower,
        delta,
        preferred: {},
      }),
    ).toEqual(expected);
  });
});
