import { renderToString } from "ink";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("shows the Work sidebar", () => {
    expect(renderToString(<App />)).toContain("Work");
  });
});
