import type Parser from "web-tree-sitter";

export interface Capture {
  name: string;
  node: Parser.SyntaxNode;
}

export function getCapture(
  captures: Capture[],
  name: string,
): Parser.SyntaxNode | null {
  const found = captures.find((c) => c.name === name);
  return found ? found.node : null;
}

export function extractClientName(
  node: Parser.SyntaxNode,
  detectNested: boolean,
): string | null {
  if (node.type === "identifier") {
    return node.text;
  }
  if (detectNested) {
    if (node.type === "member_expression" || node.type === "attribute") {
      const prop =
        node.childForFieldName("property") ||
        node.childForFieldName("attribute");
      if (prop) {
        return prop.text;
      }
    }
    if (node.type === "selector_expression") {
      const field = node.childForFieldName("field");
      if (field) {
        return field.text;
      }
    }
    if (node.type === "optional_chain_expression") {
      const inner = node.namedChildren[0];
      if (inner?.type === "member_expression") {
        const prop = inner.childForFieldName("property");
        if (prop) {
          return prop.text;
        }
      }
    }
  }
  return null;
}

export function extractIdentifier(node: Parser.SyntaxNode): string | null {
  if (node.type === "identifier") {
    return node.text;
  }
  if (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    return extractIdentifier(node.namedChildren[0]);
  }
  return null;
}

export function extractStringFromCaseValue(
  node: Parser.SyntaxNode,
): string | null {
  if (node.type === "expression_list" && node.namedChildCount > 0) {
    return extractStringFromNode(node.namedChildren[0]);
  }
  return extractStringFromNode(node);
}

export function extractStringFromNode(node: Parser.SyntaxNode): string | null {
  if (node.type === "string" || node.type === "template_string") {
    const content = node.namedChildren.find(
      (c) =>
        c.type === "string_fragment" ||
        c.type === "string_content" ||
        c.type === "string_value",
    );
    return content ? content.text : null;
  }
  if (
    node.type === "interpreted_string_literal" ||
    node.type === "raw_string_literal"
  ) {
    return node.text.slice(1, -1);
  }
  if (node.type === "string_fragment" || node.type === "string_content") {
    return node.text;
  }
  return null;
}

export function cleanStringValue(text: string): string {
  if (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'")) ||
    (text.startsWith("`") && text.endsWith("`"))
  ) {
    return text.slice(1, -1);
  }
  return text;
}

const PARAM_SKIP = new Set([
  "e",
  "ev",
  "event",
  "evt",
  "ctx",
  "context",
  "req",
  "res",
  "next",
  "err",
  "error",
  "_",
  "__",
]);

export function extractParams(paramsText: string): string[] {
  let text = paramsText.trim();
  if (text.startsWith("(")) {
    text = text.slice(1);
  }
  if (text.endsWith(")")) {
    text = text.slice(0, -1);
  }
  if (!text.trim()) {
    return [];
  }

  return text
    .split(",")
    .map((p) => {
      if (p.includes("{") || p.includes("}")) {
        return "";
      }
      const name = p.split(":")[0].split("=")[0].replace(/[?.]/g, "").trim();
      return name;
    })
    .filter((p) => p && !PARAM_SKIP.has(p) && !p.startsWith("..."));
}

export function walkNodes(
  root: Parser.SyntaxNode,
  type: string,
  callback: (node: Parser.SyntaxNode) => void,
): void {
  const visit = (node: Parser.SyntaxNode) => {
    if (node.type === type) {
      callback(node);
    }
    for (const child of node.namedChildren) {
      visit(child);
    }
  };
  visit(root);
}

const JSX_NODE_TYPES = new Set([
  "jsx_element",
  "jsx_fragment",
  "jsx_self_closing_element",
  "jsx_opening_element",
  "jsx_closing_element",
  "jsx_attribute",
]);

/**
 * Returns true when `node` lives anywhere inside a JSX element — i.e. appending
 * a trailing `// …` comment to the call's line would land inside JSX content
 * rather than in a JavaScript statement context.
 */
export function isInsideJsx(node: Parser.SyntaxNode): boolean {
  let cur: Parser.SyntaxNode | null = node.parent;
  while (cur) {
    if (JSX_NODE_TYPES.has(cur.type)) return true;
    cur = cur.parent;
  }
  return false;
}
