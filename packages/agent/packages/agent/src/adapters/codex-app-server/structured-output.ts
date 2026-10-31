/** Parse structured output from the final message, defensively (fenced block / first object). */
export function parseStructuredOutput(
  text: string,
): Record<string, unknown> | null {
  const trimmed = text.trim();
  const candidates = [trimmed];
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) candidates.push(fenced[1].trim());

  for (const candidate of candidates) {
    const parsed = parseJsonObject(candidate);
    if (parsed) return parsed;
  }

  // Fall back to the first balanced {...} in the prose. Balance-aware rather
  // than a greedy regex, so trailing prose containing braces cannot extend the
  // match past the object's real closing brace.
  let searchFrom = 0;
  for (let guard = 0; guard < 100; guard++) {
    const start = trimmed.indexOf("{", searchFrom);
    if (start === -1) return null;
    const end = findBalancedObjectEnd(trimmed, start);
    if (end === -1) return null;
    const parsed = parseJsonObject(trimmed.slice(start, end + 1));
    if (parsed) return parsed;
    searchFrom = start + 1;
  }
  return null;
}

function parseJsonObject(candidate: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(candidate);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // Not valid JSON; the caller tries the next candidate.
  }
  return null;
}

/** Index of the `}` closing the object opened at `start`, or -1 (string-aware). */
function findBalancedObjectEnd(text: string, start: number): number {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

export function toStrictOutputSchema(
  schema: Record<string, unknown>,
): Record<string, unknown> | null {
  if (!isStrictRepresentable(schema)) return null;
  return toStrictSchemaNode(schema) as Record<string, unknown>;
}

function isStrictRepresentable(node: unknown): boolean {
  if (Array.isArray(node)) return node.every(isStrictRepresentable);
  if (!isPlainObject(node)) return true;
  if (
    node.additionalProperties === true ||
    isPlainObject(node.additionalProperties) ||
    "patternProperties" in node ||
    "propertyNames" in node
  ) {
    return false;
  }
  for (const key of ["items", "anyOf", "oneOf", "allOf"]) {
    if (key in node && !isStrictRepresentable(node[key])) return false;
  }
  for (const key of ["$defs", "definitions", "properties"]) {
    const children = node[key];
    if (
      isPlainObject(children) &&
      !Object.values(children).every(isStrictRepresentable)
    ) {
      return false;
    }
  }
  return true;
}

function toStrictSchemaNode(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(toStrictSchemaNode);
  if (!isPlainObject(node)) return node;
  const result: Record<string, unknown> = { ...node };
  for (const key of ["items", "anyOf", "oneOf", "allOf"]) {
    if (key in node) result[key] = toStrictSchemaNode(node[key]);
  }
  for (const key of ["$defs", "definitions"]) {
    const defs = node[key];
    if (isPlainObject(defs)) {
      result[key] = Object.fromEntries(
        Object.entries(defs).map(([name, def]) => [
          name,
          toStrictSchemaNode(def),
        ]),
      );
    }
  }
  const properties = isPlainObject(node.properties) ? node.properties : null;
  const isObjectType =
    node.type === "object" ||
    (Array.isArray(node.type) && node.type.includes("object"));
  if (properties && !isObjectType) {
    result.properties = Object.fromEntries(
      Object.entries(properties).map(([name, property]) => [
        name,
        toStrictSchemaNode(property),
      ]),
    );
  }
  if (isObjectType) {
    const required = new Set(Array.isArray(node.required) ? node.required : []);
    if (properties) {
      result.properties = Object.fromEntries(
        Object.entries(properties).map(([name, property]) => {
          const strict = toStrictSchemaNode(property);
          return [name, required.has(name) ? strict : toNullableSchema(strict)];
        }),
      );
    }
    result.required = Object.keys(properties ?? {});
    result.additionalProperties = false;
  }
  return result;
}

export function stripSyntheticNulls(
  output: Record<string, unknown>,
  schema: Record<string, unknown>,
): Record<string, unknown> {
  return stripSyntheticNullsNode(output, schema, schema) as Record<
    string,
    unknown
  >;
}

function stripSyntheticNullsNode(
  value: unknown,
  node: unknown,
  root: Record<string, unknown>,
): unknown {
  const schema = resolveLocalRef(node, root);
  if (!isPlainObject(schema)) return value;
  if (Array.isArray(value)) {
    return isPlainObject(schema.items)
      ? value.map((item) => stripSyntheticNullsNode(item, schema.items, root))
      : value;
  }
  if (!isPlainObject(value)) return value;
  const objectBranch = singleObjectBranch(schema, root);
  if (objectBranch) return stripSyntheticNullsNode(value, objectBranch, root);
  const isObjectType =
    schema.type === "object" ||
    (Array.isArray(schema.type) && schema.type.includes("object"));
  if (!isObjectType || !isPlainObject(schema.properties)) return value;
  const properties = schema.properties;
  const required = new Set(
    Array.isArray(schema.required) ? schema.required : [],
  );
  const result: Record<string, unknown> = {};
  for (const [name, entry] of Object.entries(value)) {
    if (!(name in properties)) {
      result[name] = entry;
      continue;
    }
    if (
      entry === null &&
      !required.has(name) &&
      !acceptsNull(properties[name], root)
    ) {
      continue;
    }
    result[name] = stripSyntheticNullsNode(entry, properties[name], root);
  }
  return result;
}

function singleObjectBranch(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): unknown {
  for (const key of ["anyOf", "oneOf"]) {
    const options = schema[key];
    if (!Array.isArray(options)) continue;
    const objectOptions = options.filter((option) => {
      const resolved = resolveLocalRef(option, root);
      return (
        isPlainObject(resolved) &&
        (resolved.type === "object" ||
          (Array.isArray(resolved.type) && resolved.type.includes("object")))
      );
    });
    if (objectOptions.length === 1) return objectOptions[0];
  }
  return null;
}

function acceptsNull(node: unknown, root: Record<string, unknown>): boolean {
  const schema = resolveLocalRef(node, root);
  if (!isPlainObject(schema)) return false;
  if (schema.type === "null") return true;
  if (Array.isArray(schema.type) && schema.type.includes("null")) return true;
  if (Array.isArray(schema.enum) && schema.enum.includes(null)) return true;
  for (const key of ["anyOf", "oneOf"]) {
    const options = schema[key];
    if (
      Array.isArray(options) &&
      options.some((option) => acceptsNull(option, root))
    ) {
      return true;
    }
  }
  return false;
}

function resolveLocalRef(
  node: unknown,
  root: Record<string, unknown>,
): unknown {
  let current = node;
  for (let guard = 0; guard < 32; guard++) {
    if (!isPlainObject(current) || typeof current.$ref !== "string") {
      return current;
    }
    const match = current.$ref.match(/^#\/(\$defs|definitions)\/([^/]+)$/);
    const defs = match ? root[match[1]] : null;
    if (!match || !isPlainObject(defs)) return current;
    current = defs[match[2]];
  }
  return current;
}

function toNullableSchema(node: unknown): unknown {
  if (!isPlainObject(node)) return node;
  const result: Record<string, unknown> = { ...node };
  if (Array.isArray(node.type)) {
    if (!node.type.includes("null")) result.type = [...node.type, "null"];
  } else if (typeof node.type === "string") {
    if (node.type !== "null") result.type = [node.type, "null"];
  } else if (Array.isArray(node.anyOf)) {
    if (
      !node.anyOf.some(
        (option) => isPlainObject(option) && option.type === "null",
      )
    ) {
      result.anyOf = [...node.anyOf, { type: "null" }];
    }
  }
  if (Array.isArray(node.enum) && !node.enum.includes(null)) {
    result.enum = [...node.enum, null];
  }
  return result;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
