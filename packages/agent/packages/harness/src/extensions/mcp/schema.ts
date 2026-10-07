/**
 * JSON Schema → TypeBox conversion.
 *
 * MCP servers describe tool inputs with JSON Schema; pi tools take TypeBox
 * schemas. This converter handles the common subset used by real-world MCP
 * servers and falls back to `Type.Any()` for anything unresolvable:
 *   - Primitives (string, number, integer, boolean, null)
 *   - Arrays and objects (required/optional/additionalProperties)
 *   - String enums (via pi-ai's `StringEnum`, Google-API compatible)
 *   - Nullable types (`"type": ["string", "null"]`)
 *   - Local `$ref` (`#/$defs/...`, `#/definitions/...`)
 *   - oneOf / anyOf → Union, allOf → Intersect
 */

import { StringEnum } from "@earendil-works/pi-ai";
import type { TSchema } from "typebox";
import { Type } from "typebox";

const MAX_DEPTH = 10;

export function convertJsonSchemaToTypebox(
  schema: unknown,
  depth = 0,
  defs?: Record<string, unknown>,
): TSchema {
  // Guard against malformed schemas and runaway recursion.
  if (
    !schema ||
    typeof schema !== "object" ||
    Array.isArray(schema) ||
    depth > MAX_DEPTH
  ) {
    return Type.Any();
  }

  const s = schema as Record<string, unknown>;
  const description =
    typeof s.description === "string" ? s.description : undefined;
  const opts = description ? { description } : {};

  // $defs/definitions are carried through recursive calls for $ref resolution.
  const resolvedDefs: Record<string, unknown> = {
    ...((s.$defs ?? s.definitions) as Record<string, unknown> | undefined),
    ...defs,
  };

  if (typeof s.$ref === "string") {
    return convertRef(s.$ref, description, opts, depth, resolvedDefs);
  }

  for (const key of ["oneOf", "anyOf"] as const) {
    if (Array.isArray(s[key])) {
      const members = (s[key] as unknown[]).map((sub) =>
        convertJsonSchemaToTypebox(sub, depth + 1, resolvedDefs),
      );
      return members.length === 1
        ? (members[0] as TSchema)
        : Type.Union(members, opts);
    }
  }

  if (Array.isArray(s.allOf)) {
    const members = (s.allOf as unknown[]).map((sub) =>
      convertJsonSchemaToTypebox(sub, depth + 1, resolvedDefs),
    );
    return members.length === 1
      ? (members[0] as TSchema)
      : Type.Intersect(members, opts);
  }

  // Bare string enums: `{"enum": [...]}` with no `type` is valid JSON Schema
  // and real servers emit it — don't let it degrade to Any.
  if (
    s.type === undefined &&
    Array.isArray(s.enum) &&
    s.enum.length > 0 &&
    s.enum.every((v) => typeof v === "string")
  ) {
    return StringEnum(s.enum as string[], opts);
  }

  // Nullable types: { "type": ["string", "null"] }
  const rawType = s.type;
  const type = Array.isArray(rawType)
    ? (rawType.find((t) => t !== "null") as string | undefined)
    : typeof rawType === "string"
      ? rawType
      : undefined;
  const isNullable = Array.isArray(rawType) && rawType.includes("null");

  const base = convertByType(type, s, opts, depth, resolvedDefs);
  return isNullable ? Type.Union([base, Type.Null()]) : base;
}

function convertRef(
  ref: string,
  description: string | undefined,
  opts: Record<string, unknown>,
  depth: number,
  defs: Record<string, unknown>,
): TSchema {
  if (!ref.startsWith("#/")) {
    // External $ref — cannot resolve.
    return Type.Any(opts);
  }
  const parts = ref.slice(2).split("/");
  let resolved: unknown;
  if (parts[0] === "$defs" || parts[0] === "definitions") {
    resolved = defs[parts.slice(1).join("/")];
  } else {
    // Fallback: try the last path segment against the defs map.
    resolved = defs[parts[parts.length - 1] as string];
  }
  if (!resolved || typeof resolved !== "object") return Type.Any(opts);

  // Merge the referencing schema's description into the resolved schema.
  const merged = { ...(resolved as Record<string, unknown>) };
  if (description && !merged.description) merged.description = description;
  return convertJsonSchemaToTypebox(merged, depth + 1, defs);
}

function convertByType(
  type: string | undefined,
  s: Record<string, unknown>,
  opts: Record<string, unknown>,
  depth: number,
  defs: Record<string, unknown>,
): TSchema {
  switch (type) {
    case "string": {
      const enumVals = s.enum;
      if (
        Array.isArray(enumVals) &&
        enumVals.length > 0 &&
        enumVals.every((v) => typeof v === "string")
      ) {
        return StringEnum(enumVals as string[], opts);
      }
      return Type.String(opts);
    }
    case "number":
    case "integer":
      return Type.Number(opts);
    case "boolean":
      return Type.Boolean(opts);
    case "null":
      return Type.Null(opts);
    case "array":
      return Type.Array(
        s.items
          ? convertJsonSchemaToTypebox(s.items, depth + 1, defs)
          : Type.Unknown(),
        opts,
      );
    case "object": {
      const properties = s.properties as Record<string, unknown> | undefined;
      if (!properties) {
        // Open object — passthrough to avoid over-constraining.
        return Type.Record(Type.String(), Type.Unknown(), opts);
      }
      const required = new Set<string>(
        Array.isArray(s.required) ? (s.required as string[]) : [],
      );
      const props: Record<string, TSchema> = {};
      for (const [key, value] of Object.entries(properties)) {
        const converted = convertJsonSchemaToTypebox(value, depth + 1, defs);
        props[key] = required.has(key) ? converted : Type.Optional(converted);
      }
      const objOpts: Record<string, unknown> = { ...opts };
      if (s.additionalProperties === false) {
        objOpts.additionalProperties = false;
      }
      return Type.Object(props, objOpts);
    }
    default:
      return Type.Any(opts);
  }
}
