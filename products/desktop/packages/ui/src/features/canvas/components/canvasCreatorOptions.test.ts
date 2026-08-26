import { describe, expect, it } from "vitest";
import { buildCanvasCreatorOptions } from "./canvasCreatorOptions";

describe("buildCanvasCreatorOptions", () => {
  it("keeps the current user first and sorts each other creator once", () => {
    expect(
      buildCanvasCreatorOptions(
        [
          { createdByUuid: "b", createdBy: "Brittany Joiner" },
          { createdByUuid: "me", createdBy: "Georgiy Tarasov" },
          { createdByUuid: "a", createdBy: "Andy Vandervell" },
          { createdByUuid: "b", createdBy: "Brittany Joiner" },
        ],
        { uuid: "me", name: "Georgiy Tarasov" },
      ),
    ).toEqual([
      { value: "me", label: "Me", searchLabel: "Georgiy Tarasov" },
      { value: "", label: "Anyone" },
      { value: "a", label: "Andy Vandervell" },
      { value: "b", label: "Brittany Joiner" },
    ]);
  });
});
