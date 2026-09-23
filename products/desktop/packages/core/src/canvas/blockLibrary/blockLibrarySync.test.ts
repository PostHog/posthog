import { describe, expect, it } from "vitest";
import { componentPath } from "./blockDefinitions";
import {
  BLOCK_MANIFEST_PATH,
  hashText,
  syncBlockLibrary,
  withLibraryFile,
} from "./blockLibrarySync";
import { BLOCK_COMPONENT_SOURCES } from "./componentSources";

const METRIC_PATH = componentPath("Metric");
const OLD_COPY = "export function Metric() { return null; }\n";

function copiedEarlier(current: string): Record<string, string> {
  return {
    [METRIC_PATH]: current,
    [BLOCK_MANIFEST_PATH]: JSON.stringify({
      [METRIC_PATH]: hashText(OLD_COPY),
    }),
  };
}

describe("syncBlockLibrary", () => {
  it.each([
    {
      name: "updates an untouched copy",
      current: OLD_COPY,
      expected: BLOCK_COMPONENT_SOURCES.Metric,
    },
    {
      name: "keeps a copy someone changed",
      current: `${OLD_COPY}// edited\n`,
      expected: `${OLD_COPY}// edited\n`,
    },
  ])("$name", ({ current, expected }) => {
    expect(syncBlockLibrary(copiedEarlier(current))[METRIC_PATH]).toBe(
      expected,
    );
  });

  it("records the copy so a later sync sees it as untouched", () => {
    const files = withLibraryFile({}, METRIC_PATH);
    expect(syncBlockLibrary(files)).toBe(files);
  });
});
