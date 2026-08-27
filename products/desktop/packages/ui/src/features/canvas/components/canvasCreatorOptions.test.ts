import { describe, expect, it } from "vitest";
import { buildCanvasCreatorOptions } from "./canvasCreatorOptions";

const CURRENT_USER = { uuid: "me", name: "Georgiy Tarasov" };
const CANVASES = [
  {
    channelId: "space-b",
    createdByUuid: "b",
    createdBy: "Brittany Joiner",
  },
  {
    channelId: "space-a",
    createdByUuid: "me",
    createdBy: "Georgiy Tarasov",
  },
  {
    channelId: "space-a",
    createdByUuid: "a",
    createdBy: "Andy Vandervell",
  },
  {
    channelId: "space-b",
    createdByUuid: "b",
    createdBy: "Brittany Joiner",
  },
];

describe("buildCanvasCreatorOptions", () => {
  it("keeps the current user first and sorts each other creator once", () => {
    expect(buildCanvasCreatorOptions(CANVASES, CURRENT_USER)).toEqual([
      { value: "me", label: "Me", searchLabel: "Georgiy Tarasov" },
      { value: null, label: "Anyone" },
      { value: "a", label: "Andy Vandervell" },
      { value: "b", label: "Brittany Joiner" },
    ]);
  });

  it.each([
    {
      spaceIds: ["space-a"],
      expected: [
        { value: "me", label: "Me", searchLabel: "Georgiy Tarasov" },
        { value: null, label: "Anyone" },
        { value: "a", label: "Andy Vandervell" },
      ],
    },
    {
      spaceIds: ["space-b"],
      expected: [
        { value: null, label: "Anyone" },
        { value: "b", label: "Brittany Joiner" },
      ],
    },
  ])(
    "only includes creators with canvases in $spaceIds",
    ({ spaceIds, expected }) => {
      expect(
        buildCanvasCreatorOptions(CANVASES, CURRENT_USER, spaceIds),
      ).toEqual(expected);
    },
  );
});
