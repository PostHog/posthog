import { describe, expect, it } from "vitest";
import {
  parseStructuredOutput,
  stripSyntheticNulls,
  toStrictOutputSchema,
} from "./structured-output";

describe("parseStructuredOutput", () => {
  it("parses a bare JSON object", () => {
    expect(parseStructuredOutput('{"status": "done"}')).toEqual({
      status: "done",
    });
  });

  it("parses a fenced json code block surrounded by prose", () => {
    const text = 'Here you go:\n```json\n{"status": "done"}\n```\nAll set.';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("parses an object embedded in prose", () => {
    const text = 'The result is {"status": "done"} as requested.';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("stops at the object's real closing brace despite later braces in prose", () => {
    const text =
      'Result: {"status": "done"} and note that {braces} appear later }';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("skips a non-JSON brace group before the real object", () => {
    const text = 'A {rough} answer: {"status": "done"}';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("handles braces inside JSON strings", () => {
    const text = 'Answer: {"note": "uses { and } inside"} trailing prose';
    expect(parseStructuredOutput(text)).toEqual({
      note: "uses { and } inside",
    });
  });

  it("returns null for an array, plain prose, or an unclosed object", () => {
    expect(parseStructuredOutput("[1, 2, 3]")).toBeNull();
    expect(parseStructuredOutput("no json here")).toBeNull();
    expect(parseStructuredOutput('leading {"a": 1')).toBeNull();
  });
});

describe("toStrictOutputSchema", () => {
  it("closes nested objects and requires every property", () => {
    const schema = {
      type: "object",
      properties: {
        repo: {
          type: "object",
          properties: { name: { type: "string" } },
          required: ["name"],
        },
      },
      required: ["repo"],
    };
    expect(toStrictOutputSchema(schema)).toEqual({
      type: "object",
      properties: {
        repo: {
          type: "object",
          properties: { name: { type: "string" } },
          required: ["name"],
          additionalProperties: false,
        },
      },
      required: ["repo"],
      additionalProperties: false,
    });
  });

  it("closes objects inside arrays, anyOf and $defs", () => {
    const strict = toStrictOutputSchema({
      type: "object",
      properties: {
        rows: {
          type: "array",
          items: { type: "object", properties: { id: { type: "number" } } },
        },
        choice: { anyOf: [{ $ref: "#/$defs/thing" }, { type: "string" }] },
      },
      required: ["rows", "choice"],
      $defs: { thing: { type: "object", properties: {} } },
    });
    expect(strict).toMatchObject({
      properties: {
        rows: {
          items: {
            properties: { id: { type: ["number", "null"] } },
            required: ["id"],
            additionalProperties: false,
          },
        },
      },
      $defs: { thing: { required: [], additionalProperties: false } },
    });
  });

  it("makes optional properties required but nullable", () => {
    const strict = toStrictOutputSchema({
      type: "object",
      properties: {
        name: { type: "string" },
        label: { type: "string", enum: ["a", "b"] },
        value: { anyOf: [{ type: "string" }, { type: "number" }] },
      },
      required: ["name"],
    });
    expect(strict).toEqual({
      type: "object",
      properties: {
        name: { type: "string" },
        label: { type: ["string", "null"], enum: ["a", "b", null] },
        value: {
          anyOf: [{ type: "string" }, { type: "number" }, { type: "null" }],
        },
      },
      required: ["name", "label", "value"],
      additionalProperties: false,
    });
  });

  it("leaves the input schema untouched", () => {
    const schema = {
      type: "object",
      properties: {
        nested: { type: "object", properties: { a: { type: "string" } } },
      },
    };
    const before = structuredClone(schema);
    toStrictOutputSchema(schema);
    expect(schema).toEqual(before);
  });

  it.each([
    [
      "a top-level dictionary",
      {
        type: "object",
        additionalProperties: { type: "string" },
        minProperties: 1,
      },
    ],
    [
      "a nested dictionary",
      {
        type: "object",
        properties: {
          labels: {
            type: "object",
            additionalProperties: { type: "string" },
            minProperties: 1,
          },
        },
        required: ["labels"],
      },
    ],
    [
      "a dictionary behind $defs",
      {
        type: "object",
        properties: { rows: { type: "array", items: { $ref: "#/$defs/m" } } },
        $defs: { m: { type: "object", additionalProperties: true } },
      },
    ],
    [
      "patternProperties",
      { type: "object", patternProperties: { "^x-": { type: "string" } } },
    ],
  ])("returns null for %s, which strict mode cannot represent", (_, schema) => {
    expect(toStrictOutputSchema(schema)).toBeNull();
  });

  it("still converts a schema that already sets additionalProperties: false", () => {
    expect(
      toStrictOutputSchema({
        type: "object",
        properties: { name: { type: "string" } },
        additionalProperties: false,
      }),
    ).toEqual({
      type: "object",
      properties: { name: { type: ["string", "null"] } },
      required: ["name"],
      additionalProperties: false,
    });
  });
});

describe("stripSyntheticNulls", () => {
  const schema = {
    type: "object",
    properties: {
      note: { type: "string" },
      reason: { type: ["string", "null"] },
      owner: { type: ["string", "null"] },
      kind: { enum: ["a", null] },
      repo: {
        type: "object",
        properties: { name: { type: "string" }, branch: { type: "string" } },
        required: ["name"],
      },
      rows: { type: "array", items: { $ref: "#/$defs/row" } },
      parent: { anyOf: [{ $ref: "#/$defs/row" }, { type: "null" }] },
    },
    required: ["owner"],
    $defs: {
      row: {
        type: "object",
        properties: { id: { type: "number" }, tag: { type: "string" } },
        required: ["id"],
      },
    },
  };

  it("drops nulls the original schema rejects and keeps the ones it accepts", () => {
    expect(
      stripSyntheticNulls(
        {
          note: null,
          reason: null,
          owner: null,
          kind: null,
          repo: { name: "posthog", branch: null },
          rows: [
            { id: 1, tag: null },
            { id: 2, tag: "x" },
          ],
          parent: { id: 3, tag: null },
          extra: null,
        },
        schema,
      ),
    ).toEqual({
      reason: null,
      owner: null,
      kind: null,
      repo: { name: "posthog" },
      rows: [{ id: 1 }, { id: 2, tag: "x" }],
      parent: { id: 3 },
      extra: null,
    });
  });

  it("keeps a null for a required property", () => {
    const strict = {
      type: "object",
      properties: { note: { type: "string" } },
      required: ["note"],
    };
    expect(stripSyntheticNulls({ note: null }, strict)).toEqual({
      note: null,
    });
  });

  it("leaves the input output and schema untouched", () => {
    const output = { note: null, repo: { name: "posthog", branch: null } };
    const before = structuredClone(output);
    const schemaBefore = structuredClone(schema);
    stripSyntheticNulls(output, schema);
    expect(output).toEqual(before);
    expect(schema).toEqual(schemaBefore);
  });
});
