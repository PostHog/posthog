import type {
  SourceConfig,
  SourceFieldConfig,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { buildPayload, missingRequiredFields } from "./dynamicSourceFields";

const MULTIPLE_SELECT: SourceFieldConfig = {
  type: "select",
  name: "result_types",
  label: "Result types",
  required: true,
  multiple: true,
  defaultValue: "web",
  options: [
    { label: "Web", value: "web" },
    { label: "Image", value: "image" },
    { label: "Video", value: "video" },
  ],
};

const PLAIN_SELECT: SourceFieldConfig = {
  type: "select",
  name: "api_base_url",
  label: "API base URL",
  required: false,
  defaultValue: "https://api.example.com",
  options: [
    { label: "https://api.example.com", value: "https://api.example.com" },
    { label: "https://eu.example.com", value: "https://eu.example.com" },
  ],
};

const BRANCHED_SELECT: SourceFieldConfig = {
  type: "select",
  name: "auth_method",
  label: "Authentication",
  required: true,
  defaultValue: "api_key",
  options: [
    {
      label: "API key",
      value: "api_key",
      fields: [
        { type: "password", name: "api_key", label: "API key", required: true },
      ],
    },
    { label: "OAuth", value: "oauth" },
  ],
};

function sourceConfig(...fields: SourceFieldConfig[]): SourceConfig {
  return { name: "TestSource", fields };
}

describe("dynamicSourceFields", () => {
  it.each([
    [
      "a multiple select as a list",
      sourceConfig(MULTIPLE_SELECT),
      { result_types: ["image", "video"] },
      { result_types: ["image", "video"] },
    ],
    [
      "an untouched multiple select as its default list",
      sourceConfig(MULTIPLE_SELECT),
      {},
      { result_types: ["web"] },
    ],
    [
      "a plain select as a bare value",
      sourceConfig(PLAIN_SELECT),
      {},
      { api_base_url: "https://api.example.com" },
    ],
    [
      "a branched select under selection",
      sourceConfig(BRANCHED_SELECT),
      { auth_method: "api_key", api_key: "not-a-real-key" },
      { auth_method: { selection: "api_key", api_key: "not-a-real-key" } },
    ],
  ] as [string, SourceConfig, Record<string, string | string[]>, unknown][])(
    "submits %s",
    (_name, config, values, expected) => {
      expect(buildPayload(config, values)).toEqual(expected);
    },
  );

  it("blocks submit while a required multiple select has nothing selected", () => {
    const config = sourceConfig(MULTIPLE_SELECT);

    expect(missingRequiredFields(config, { result_types: [] })).toEqual([
      "result_types",
    ]);
    expect(missingRequiredFields(config, { result_types: ["web"] })).toEqual(
      [],
    );
  });
});
