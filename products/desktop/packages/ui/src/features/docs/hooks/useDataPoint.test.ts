import { describe, expect, it } from "vitest";
import { readQueryError } from "./useDataPoint";

describe("readQueryError", () => {
  it.each([
    [
      'Failed request: [400] {"type":"validation_error","code":"hogql_syntax_error","detail":"expected identifier after \'.\', got Dot","attr":null}',
      "This query did not run: expected identifier after '.', got Dot",
    ],
    ["<!DOCTYPE html><html>Server Error</html>", "This query did not run."],
    ["Network down", "Network down"],
  ])("turns %j into one line for the reader", (message, expected) => {
    expect(readQueryError(new Error(message))).toBe(expected);
  });
});
