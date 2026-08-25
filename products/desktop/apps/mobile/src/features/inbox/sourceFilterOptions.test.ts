import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { EXTERNAL_INBOX_SOURCES, type SourceProduct } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  narrowSourceProductOptions,
  SOURCE_PRODUCT_OPTIONS,
} from "./sourceFilterOptions";

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

function config(
  source_product: SourceProduct,
  enabled: boolean,
): SignalSourceConfig {
  return {
    id: source_product,
    source_product,
    source_type: "issue",
    enabled,
    config: {},
    created_at: "",
    updated_at: "",
    status: null,
  };
}

describe("narrowSourceProductOptions", () => {
  const values = (
    configs: SignalSourceConfig[] | undefined,
    selected: SourceProduct[] = [],
  ) => narrowSourceProductOptions(configs, selected).map((o) => o.value);

  it("shows an enabled warehouse source and hides a disabled one", () => {
    const result = values([config("github", true), config("sentry", false)]);
    expect(result).toContain("github");
    expect(result).not.toContain("sentry");
  });

  it("always keeps PostHog's own products", () => {
    const result = values([]);
    expect(result).toContain("session_replay");
    expect(result).toContain("signals_scout");
    expect(result).not.toContain("github");
  });

  it("keeps a disabled source while it is selected", () => {
    const result = values([config("sentry", false)], ["sentry"]);
    expect(result).toContain("sentry");
  });

  it("hides nothing while the source configs are unknown", () => {
    expect(values(undefined)).toEqual(
      SOURCE_PRODUCT_OPTIONS.map((o) => o.value),
    );
  });
});
