import type Parser from "web-tree-sitter";
import { findAliases, getEffectiveClients } from "./alias-resolver.js";
import {
  extractClientName,
  extractStringFromNode,
  getCapture,
} from "./ast-helpers.js";
import type { LangFamily } from "./languages.js";
import type { ParserManager } from "./parser-manager.js";
import type { LocalWrapper, WrapperClassification } from "./types.js";

const CONTROL_FLOW_KEYWORDS = new Set([
  "if",
  "for",
  "while",
  "switch",
  "catch",
  "else",
]);

type KeyArgLocator = {
  /** Zero-based positional arg index that carries the event/flag key for this method. */
  positionalIndex: number;
  /** Python/Ruby keyword-arg name that may carry the key instead of a positional. */
  kwargName?: string;
};

function getKeyArgLocator(
  method: string,
  family: LangFamily,
  languageId: string,
): KeyArgLocator | null {
  if (languageId === "python") {
    if (family.captureMethods.has(method)) {
      return { positionalIndex: 1, kwargName: "event" };
    }
    if (family.flagMethods.has(method)) {
      return { positionalIndex: 0, kwargName: "key" };
    }
    return null;
  }
  // JS / TS / TSX / JSX: first positional for all SDK methods.
  if (family.allMethods.has(method)) {
    return { positionalIndex: 0 };
  }
  return null;
}

function extractRawParams(
  paramsNode: Parser.SyntaxNode | null,
  singleParamNode: Parser.SyntaxNode | null,
  languageId: string,
): string[] {
  if (singleParamNode) {
    return [singleParamNode.text];
  }
  if (!paramsNode) {
    return [];
  }
  const names: string[] = [];
  for (const child of paramsNode.namedChildren) {
    const n = extractParamName(child, languageId);
    if (n) {
      names.push(n);
    } else {
      names.push("");
    }
  }
  return names;
}

function extractParamName(
  node: Parser.SyntaxNode,
  languageId: string,
): string | null {
  switch (node.type) {
    case "identifier":
      return node.text;
    case "required_parameter":
    case "optional_parameter": {
      const pat = node.childForFieldName("pattern");
      if (pat) return extractParamName(pat, languageId);
      const name = node.childForFieldName("name");
      if (name) return extractParamName(name, languageId);
      const id = node.namedChildren.find((c) => c.type === "identifier");
      return id?.text ?? null;
    }
    case "assignment_pattern": {
      const left = node.childForFieldName("left");
      return left ? extractParamName(left, languageId) : null;
    }
    case "typed_parameter":
    case "default_parameter":
    case "typed_default_parameter": {
      const name = node.childForFieldName("name");
      if (name) return extractParamName(name, languageId);
      const id = node.namedChildren.find((c) => c.type === "identifier");
      return id?.text ?? null;
    }
    case "parameter": {
      const id = node.namedChildren.find(
        (c) => c.type === "identifier" || c.type === "field_identifier",
      );
      return id?.text ?? null;
    }
    default: {
      const id = node.namedChildren.find((c) => c.type === "identifier");
      return id?.text ?? null;
    }
  }
}

interface PostHogCallInBody {
  method: string;
  keyArgNode: Parser.SyntaxNode | null;
  kwargName: string | null;
}

function findPostHogCallInBody(
  body: Parser.SyntaxNode,
  allClients: Set<string>,
  family: LangFamily,
  languageId: string,
  detectNested: boolean,
): PostHogCallInBody | null {
  let found: PostHogCallInBody | null = null;

  const visit = (node: Parser.SyntaxNode) => {
    if (found) return;

    const call = matchPostHogCall(
      node,
      allClients,
      family,
      languageId,
      detectNested,
    );
    if (call) {
      found = call;
      return;
    }

    for (const child of node.namedChildren) {
      if (found) return;
      visit(child);
    }
  };

  visit(body);
  return found;
}

function matchPostHogCall(
  node: Parser.SyntaxNode,
  allClients: Set<string>,
  family: LangFamily,
  languageId: string,
  detectNested: boolean,
): PostHogCallInBody | null {
  if (node.type !== "call_expression" && node.type !== "call") return null;
  const funcNode = node.childForFieldName("function");
  if (!funcNode) return null;

  let method: string | null = null;
  if (funcNode.type === "member_expression" || funcNode.type === "attribute") {
    const objNode =
      funcNode.childForFieldName("object") ||
      funcNode.childForFieldName("operand");
    const propNode =
      funcNode.childForFieldName("property") ||
      funcNode.childForFieldName("attribute");
    if (!objNode || !propNode) return null;
    const clientName = extractClientName(objNode, detectNested);
    if (!clientName || !allClients.has(clientName)) return null;
    method = propNode.text;
  } else if (funcNode.type === "selector_expression") {
    const opNode = funcNode.childForFieldName("operand");
    const fieldNode = funcNode.childForFieldName("field");
    if (!opNode || !fieldNode) return null;
    const clientName = extractClientName(opNode, detectNested);
    if (!clientName || !allClients.has(clientName)) return null;
    method = fieldNode.text;
  } else {
    return null;
  }

  if (!method || !family.allMethods.has(method)) return null;

  const locator = getKeyArgLocator(method, family, languageId);
  if (!locator) return null;

  const argsNode =
    node.childForFieldName("arguments") ||
    node.namedChildren.find(
      (c) => c.type === "arguments" || c.type === "argument_list",
    ) ||
    null;
  if (!argsNode) return null;

  const { keyNode, kwargName } = pickKeyArg(argsNode, locator);
  return {
    method,
    keyArgNode: keyNode,
    kwargName,
  };
}

function pickKeyArg(
  argsNode: Parser.SyntaxNode,
  locator: KeyArgLocator,
): { keyNode: Parser.SyntaxNode | null; kwargName: string | null } {
  const positional: Parser.SyntaxNode[] = [];
  let kwargHit: Parser.SyntaxNode | null = null;
  let kwargName: string | null = null;

  for (const child of argsNode.namedChildren) {
    if (child.type === "keyword_argument") {
      const nameNode = child.childForFieldName("name");
      const valueNode = child.childForFieldName("value");
      if (
        nameNode &&
        valueNode &&
        locator.kwargName &&
        nameNode.text === locator.kwargName
      ) {
        kwargHit = valueNode;
        kwargName = nameNode.text;
      }
      continue;
    }
    positional.push(child);
  }

  if (kwargHit) {
    return { keyNode: kwargHit, kwargName };
  }
  const positionalHit = positional[locator.positionalIndex] ?? null;
  return { keyNode: positionalHit, kwargName: null };
}

function classifyKeyArg(
  keyArgNode: Parser.SyntaxNode | null,
  params: string[],
): WrapperClassification | null {
  if (!keyArgNode) return null;

  if (
    keyArgNode.type === "string" ||
    keyArgNode.type === "interpreted_string_literal"
  ) {
    const key = extractStringFromNode(keyArgNode);
    return key !== null ? { kind: "fixed-key", key } : null;
  }
  if (keyArgNode.type === "template_string") {
    const hasInterpolation = keyArgNode.namedChildren.some(
      (c) => c.type === "template_substitution",
    );
    if (hasInterpolation) return null;
    const key = extractStringFromNode(keyArgNode);
    return key !== null ? { kind: "fixed-key", key } : null;
  }

  if (keyArgNode.type === "identifier") {
    const idx = params.indexOf(keyArgNode.text);
    if (idx >= 0) return { kind: "pass-through", paramIndex: idx };
    return null;
  }

  return null;
}

function getExportStatus(
  nameNode: Parser.SyntaxNode,
  languageId: string,
): { isDefaultExport: boolean; isNamedExport: boolean } {
  // Walk up starting from the wrapper's own definition node (nameNode.parent).
  // Skip it so we examine its surrounding context, not itself.
  const defNode = nameNode.parent;
  if (!defNode) return { isDefaultExport: false, isNamedExport: false };

  if (languageId === "python") {
    let cur: Parser.SyntaxNode | null = defNode.parent;
    while (cur) {
      if (cur.type === "module") {
        return { isDefaultExport: false, isNamedExport: true };
      }
      if (
        cur.type === "function_definition" ||
        cur.type === "class_definition"
      ) {
        return { isDefaultExport: false, isNamedExport: false };
      }
      cur = cur.parent;
    }
    return { isDefaultExport: false, isNamedExport: false };
  }

  let cur: Parser.SyntaxNode | null = defNode.parent;
  while (cur) {
    if (cur.type === "export_statement") {
      const hasDefault = cur.children.some((c) => c.type === "default");
      return { isDefaultExport: hasDefault, isNamedExport: !hasDefault };
    }
    if (cur.type === "program" || cur.type === "module") break;
    cur = cur.parent;
  }
  return { isDefaultExport: false, isNamedExport: false };
}

export async function findWrappers(
  pm: ParserManager,
  source: string,
  languageId: string,
): Promise<LocalWrapper[]> {
  const ready = await pm.ensureReady(languageId);
  if (!ready) return [];

  const { lang, family } = ready;
  const tree = pm.parse(source, lang);
  if (!tree) return [];

  const functionQuery = pm.getQuery(lang, family.queries.functions);
  if (!functionQuery) return [];

  const allClients = getEffectiveClients(pm.config);
  const { clientAliases } = findAliases(pm, lang, tree, family);
  for (const a of clientAliases) allClients.add(a);

  const wrappers: LocalWrapper[] = [];
  const seen = new Set<string>();

  for (const match of functionQuery.matches(tree.rootNode)) {
    const nameNode = getCapture(match.captures, "func_name");
    const paramsNode = getCapture(match.captures, "func_params");
    const singleParamNode = getCapture(match.captures, "func_single_param");
    const bodyNode = getCapture(match.captures, "func_body");
    if (!nameNode || !bodyNode) continue;

    const name = nameNode.text;
    if (CONTROL_FLOW_KEYWORDS.has(name)) continue;
    if (seen.has(name)) continue;

    const params = extractRawParams(paramsNode, singleParamNode, languageId);

    const call = findPostHogCallInBody(
      bodyNode,
      allClients,
      family,
      languageId,
      pm.config.detectNestedClients,
    );
    if (!call) continue;

    const classification = classifyKeyArg(call.keyArgNode, params);
    if (!classification) continue;

    const methodKind = family.captureMethods.has(call.method)
      ? "capture"
      : "flag";
    const posthogMethod = call.method === "Enqueue" ? "capture" : call.method;

    const exportStatus = getExportStatus(nameNode, languageId);
    seen.add(name);

    wrappers.push({
      name,
      methodKind,
      posthogMethod,
      classification,
      ...exportStatus,
    });
  }

  return wrappers;
}
