import { EXTERNAL_INBOX_SOURCES } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { SOURCE_PRODUCT_OPTIONS } from "./FilterSheet";

describe("SOURCE_PRODUCT_OPTIONS", () => {
  it("includes every warehouse-backed source from the shared registry", () => {
    const values = new Set(SOURCE_PRODUCT_OPTIONS.map((o) => o.value));
    for (const source of EXTERNAL_INBOX_SOURCES) {
      expect(values.has(source.product)).toBe(true);
    }
  });

  it("keeps the native products", () => {
    const values = SOURCE_PRODUCT_OPTIONS.map((o) => o.value);
    expect(values).toContain("session_replay");
    expect(values).toContain("signals_scout");
  });
});
