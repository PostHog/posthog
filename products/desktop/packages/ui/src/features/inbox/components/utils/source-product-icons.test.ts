import { describe, expect, it } from "vitest";
import { getSourceProductMeta } from "./source-product-icons";

describe("source product display metadata", () => {
  it("labels a report-check failure", () => {
    expect(getSourceProductMeta("signals_check")?.label).toBe("Report checks");
  });
});
