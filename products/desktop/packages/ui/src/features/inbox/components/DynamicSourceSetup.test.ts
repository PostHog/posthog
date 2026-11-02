import type { SourceConfig } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { buildPayload } from "./DynamicSourceSetup";

const flatSelectConfig = {
  name: "Datadog",
  fields: [
    {
      type: "select",
      name: "site",
      label: "Datadog site",
      required: true,
      defaultValue: "datadoghq.com",
      options: [
        { label: "US1", value: "datadoghq.com" },
        { label: "EU1", value: "datadoghq.eu" },
      ],
    },
  ],
} as unknown as SourceConfig;

const nestedSelectConfig = {
  name: "Example",
  fields: [
    {
      type: "select",
      name: "auth_method",
      label: "Auth method",
      required: true,
      defaultValue: "api_key",
      options: [
        {
          label: "API key",
          value: "api_key",
          fields: [
            { type: "text", name: "api_key", label: "API key", required: true },
          ],
        },
        { label: "OAuth", value: "oauth" },
      ],
    },
  ],
} as unknown as SourceConfig;

describe("buildPayload", () => {
  it.each<{
    name: string;
    config: SourceConfig;
    values: Parameters<typeof buildPayload>[1];
    expected: Record<string, unknown>;
  }>([
    {
      name: "flat select sends the chosen value",
      config: flatSelectConfig,
      values: { site: "datadoghq.eu" },
      expected: { site: "datadoghq.eu" },
    },
    {
      name: "flat select falls back to the default",
      config: flatSelectConfig,
      values: {},
      expected: { site: "datadoghq.com" },
    },
    {
      name: "select with option fields nests the selection",
      config: nestedSelectConfig,
      values: { auth_method: "api_key", api_key: " secret " },
      expected: { auth_method: { selection: "api_key", api_key: "secret" } },
    },
  ])("$name", ({ config, values, expected }) => {
    expect(buildPayload(config, values)).toEqual(expected);
  });
});
