import { describe, expect, it } from "vitest";
import { convertJsonSchemaToTypebox } from "./schema";

// TypeBox's TSchema doesn't expose JSON Schema keywords structurally; the
// tests assert on the emitted JSON Schema shape, so widen the return type.
interface JsonSchemaShape {
  type?: string;
  description?: string;
  enum?: string[];
  items?: JsonSchemaShape;
  properties?: Record<string, JsonSchemaShape>;
  required?: string[];
  additionalProperties?: unknown;
  patternProperties?: unknown;
  anyOf?: JsonSchemaShape[];
  allOf?: JsonSchemaShape[];
}

function convert(input: unknown): JsonSchemaShape {
  return convertJsonSchemaToTypebox(input) as JsonSchemaShape;
}

describe("convertJsonSchemaToTypebox", () => {
  it.each([
    ["string", { type: "string" }, { type: "string" }],
    ["number", { type: "number" }, { type: "number" }],
    ["integer", { type: "integer" }, { type: "number" }],
    ["boolean", { type: "boolean" }, { type: "boolean" }],
    ["null", { type: "null" }, { type: "null" }],
  ])("converts %s", (_label, input, expected) => {
    expect(convert(input)).toMatchObject(expected);
  });

  it("preserves descriptions", () => {
    const result = convert({
      type: "string",
      description: "a name",
    });
    expect(result.description).toBe("a name");
  });

  it("converts string enums to a Google-compatible enum schema", () => {
    const result = convert({
      type: "string",
      enum: ["a", "b"],
    });
    // StringEnum produces { type: "string", enum: [...] }, not a union of
    // literals (which Google's API rejects).
    expect(result).toMatchObject({ type: "string", enum: ["a", "b"] });
  });

  it("converts bare enums without a type keyword", () => {
    // Valid JSON Schema that real servers emit; must not degrade to Any.
    expect(convert({ enum: ["a", "b"] })).toMatchObject({
      type: "string",
      enum: ["a", "b"],
    });
  });

  it("converts arrays with item schemas", () => {
    const result = convert({
      type: "array",
      items: { type: "number" },
    });
    expect(result).toMatchObject({
      type: "array",
      items: { type: "number" },
    });
  });

  it("converts objects with required and optional properties", () => {
    const result = convert({
      type: "object",
      properties: {
        name: { type: "string" },
        age: { type: "number" },
      },
      required: ["name"],
    });
    expect(result.type).toBe("object");
    expect(result.required).toEqual(["name"]);
    expect(result.properties?.name).toMatchObject({ type: "string" });
    expect(result.properties?.age).toMatchObject({ type: "number" });
  });

  it("respects additionalProperties: false", () => {
    const result = convert({
      type: "object",
      properties: { a: { type: "string" } },
      additionalProperties: false,
    });
    expect(result.additionalProperties).toBe(false);
  });

  it("converts objects without properties to an open record", () => {
    const result = convert({ type: "object" });
    expect(result.type).toBe("object");
    expect(
      result.patternProperties ?? result.additionalProperties,
    ).toBeDefined();
  });

  it("converts nullable types to a union with null", () => {
    const result = convert({ type: ["string", "null"] });
    expect(result.anyOf).toHaveLength(2);
    expect(result.anyOf?.[0]).toMatchObject({ type: "string" });
    expect(result.anyOf?.[1]).toMatchObject({ type: "null" });
  });

  it.each([["oneOf"], ["anyOf"]])("converts %s to a union", (key) => {
    const result = convert({
      [key]: [{ type: "string" }, { type: "number" }],
    });
    expect(result.anyOf).toHaveLength(2);
  });

  it("unwraps single-member unions", () => {
    const result = convert({ anyOf: [{ type: "string" }] });
    expect(result).toMatchObject({ type: "string" });
  });

  it("converts allOf to an intersection", () => {
    const result = convert({
      allOf: [
        { type: "object", properties: { a: { type: "string" } } },
        { type: "object", properties: { b: { type: "number" } } },
      ],
    });
    expect(result.allOf).toHaveLength(2);
  });

  it("resolves local $refs through $defs", () => {
    const result = convert({
      type: "object",
      properties: {
        pet: { $ref: "#/$defs/Pet", description: "the pet" },
      },
      required: ["pet"],
      $defs: {
        Pet: { type: "object", properties: { name: { type: "string" } } },
      },
    });
    expect(result.properties?.pet?.type).toBe("object");
    expect(result.properties?.pet?.description).toBe("the pet");
    expect(result.properties?.pet?.properties?.name).toMatchObject({
      type: "string",
    });
  });

  it.each([
    ["unresolvable $ref", { $ref: "#/$defs/Missing" }],
    ["external $ref", { $ref: "https://example.com/schema.json" }],
    ["missing type", { foo: "bar" }],
    ["non-object schema", "nonsense"],
    ["null schema", null],
  ])("falls back to Any for %s", (_label, input) => {
    const result = convert(input);
    expect(result.type).toBeUndefined();
  });

  it("guards against runaway recursion depth", () => {
    // Build a deeply nested array schema beyond the depth limit.
    let schema: Record<string, unknown> = { type: "string" };
    for (let i = 0; i < 20; i++) {
      schema = { type: "array", items: schema };
    }
    const result = convert(schema);
    // Should terminate and produce a valid schema.
    expect(result.type).toBe("array");
  });
});
