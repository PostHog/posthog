import { describe, expect, it } from "vitest";
import { BLOCK_RUNTIME_PATH, componentPath } from "./blockDefinitions";
import {
  BLOCK_MANIFEST_PATH,
  hashText,
  syncBlockLibrary,
  withLibraryFile,
} from "./blockLibrarySync";
import { BLOCK_COMPONENT_SOURCES } from "./componentSources";
import { BLOCK_RUNTIME_SOURCE } from "./runtimeSource";

const METRIC_PATH = componentPath("Metric");
const OLD_COPY = "export function Metric() { return null; }\n";

function copiedEarlier(
  current: string,
  runtime?: string,
): Record<string, string> {
  return {
    [METRIC_PATH]: current,
    ...(runtime === undefined ? {} : { [BLOCK_RUNTIME_PATH]: runtime }),
    [BLOCK_MANIFEST_PATH]: JSON.stringify({
      [METRIC_PATH]: hashText(OLD_COPY),
      ...(runtime === undefined
        ? {}
        : { [BLOCK_RUNTIME_PATH]: hashText(BLOCK_RUNTIME_SOURCE) }),
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
    {
      name: "keeps every copy when someone changed the runtime",
      current: OLD_COPY,
      runtime: `${BLOCK_RUNTIME_SOURCE}// edited\n`,
      expected: OLD_COPY,
    },
  ])("$name", ({ current, runtime, expected }) => {
    expect(syncBlockLibrary(copiedEarlier(current, runtime))[METRIC_PATH]).toBe(
      expected,
    );
  });

  it("records the copy so a later sync sees it as untouched", () => {
    const files = withLibraryFile({}, METRIC_PATH);
    expect(syncBlockLibrary(files)).toBe(files);
  });
});
