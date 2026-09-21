import type Parser from "web-tree-sitter";
import { cleanStringValue, getCapture } from "./ast-helpers.js";
import type { LangFamily } from "./languages.js";
import { CLIENT_NAMES } from "./languages.js";
import type { ParserManager } from "./parser-manager.js";
import type { DetectionConfig } from "./types.js";

const POSTHOG_CLASS_NAMES = new Set(["PostHog", "Posthog"]);
const GO_CONSTRUCTOR_NAMES = new Set(["New", "NewWithConfig"]);

export function getEffectiveClients(config: DetectionConfig): Set<string> {
  const clients = new Set(CLIENT_NAMES);
  for (const name of config.additionalClientNames) {
    clients.add(name);
  }
  return clients;
}

export function findAliases(
  pm: ParserManager,
  lang: Parser.Language,
  tree: Parser.Tree,
  family: LangFamily,
): {
  clientAliases: Set<string>;
  destructuredCapture: Set<string>;
  destructuredFlag: Set<string>;
} {
  const effectiveClients = getEffectiveClients(pm.config);
  const clientAliases = new Set<string>();
  const destructuredCapture = new Set<string>();
  const destructuredFlag = new Set<string>();

  // Client aliases: const tracker = posthog
  const aliasQuery = pm.getQuery(lang, family.queries.clientAliases);
  if (aliasQuery) {
    for (const match of aliasQuery.matches(tree.rootNode)) {
      const aliasNode = getCapture(match.captures, "alias");
      const sourceNode = getCapture(match.captures, "source");
      if (aliasNode && sourceNode && effectiveClients.has(sourceNode.text)) {
        clientAliases.add(aliasNode.text);
      }
    }
  }

  // Constructor aliases: new PostHog('phc_...') / posthog.New("token") / PostHog::Client.new(...)
  const constructorQuery = pm.getQuery(lang, family.queries.constructorAliases);
  if (constructorQuery) {
    for (const match of constructorQuery.matches(tree.rootNode)) {
      const aliasNode = getCapture(match.captures, "alias");
      const classNode = getCapture(match.captures, "class_name");
      const pkgNode = getCapture(match.captures, "pkg_name");
      const funcNode = getCapture(match.captures, "func_name");

      if (aliasNode && classNode && POSTHOG_CLASS_NAMES.has(classNode.text)) {
        clientAliases.add(aliasNode.text);
      }
      if (
        aliasNode &&
        pkgNode &&
        funcNode &&
        pkgNode.text === "posthog" &&
        GO_CONSTRUCTOR_NAMES.has(funcNode.text)
      ) {
        clientAliases.add(aliasNode.text);
      }
      const scopeNode = getCapture(match.captures, "scope_name");
      const methodNameNode = getCapture(match.captures, "method_name");
      if (
        aliasNode &&
        scopeNode &&
        classNode &&
        methodNameNode &&
        POSTHOG_CLASS_NAMES.has(scopeNode.text) &&
        classNode.text === "Client" &&
        methodNameNode.text === "new"
      ) {
        clientAliases.add(aliasNode.text);
      }
    }
  }

  // Destructured methods: const { capture, getFeatureFlag } = posthog
  if (family.queries.destructuredMethods) {
    const destructQuery = pm.getQuery(lang, family.queries.destructuredMethods);
    if (destructQuery) {
      for (const match of destructQuery.matches(tree.rootNode)) {
        const methodNode = getCapture(match.captures, "method_name");
        const sourceNode = getCapture(match.captures, "source");
        if (methodNode && sourceNode && effectiveClients.has(sourceNode.text)) {
          const name = methodNode.text;
          if (family.captureMethods.has(name)) {
            destructuredCapture.add(name);
          }
          if (family.flagMethods.has(name)) {
            destructuredFlag.add(name);
          }
        }
      }
    }
  }

  return { clientAliases, destructuredCapture, destructuredFlag };
}

export function buildConstantMap(
  pm: ParserManager,
  lang: Parser.Language,
  tree: Parser.Tree,
): Map<string, string> {
  const constants = new Map<string, string>();

  // JS: const/let/var declarations
  const jsQuery = pm.getQuery(
    lang,
    `
    (lexical_declaration
      (variable_declarator
        name: (identifier) @name
        value: (string (string_fragment) @value)))

    (variable_declaration
      (variable_declarator
        name: (identifier) @name
        value: (string (string_fragment) @value)))
    `,
  );
  if (jsQuery) {
    for (const match of jsQuery.matches(tree.rootNode)) {
      const nameNode = getCapture(match.captures, "name");
      const valueNode = getCapture(match.captures, "value");
      if (nameNode && valueNode) {
        constants.set(nameNode.text, valueNode.text);
      }
    }
  }

  // Python: simple assignment — NAME = "value"
  const pyQuery = pm.getQuery(
    lang,
    `
    (expression_statement
      (assignment
        left: (identifier) @name
        right: (string (string_content) @value)))
    `,
  );
  if (pyQuery) {
    for (const match of pyQuery.matches(tree.rootNode)) {
      const nameNode = getCapture(match.captures, "name");
      const valueNode = getCapture(match.captures, "value");
      if (nameNode && valueNode) {
        constants.set(nameNode.text, valueNode.text);
      }
    }
  }

  // Go: short var declarations and const declarations
  const goVarQuery = pm.getQuery(
    lang,
    `
    (short_var_declaration
      left: (expression_list (identifier) @name)
      right: (expression_list (interpreted_string_literal) @value))
    `,
  );
  if (goVarQuery) {
    for (const match of goVarQuery.matches(tree.rootNode)) {
      const nameNode = getCapture(match.captures, "name");
      const valueNode = getCapture(match.captures, "value");
      if (nameNode && valueNode) {
        constants.set(nameNode.text, cleanStringValue(valueNode.text));
      }
    }
  }

  const goConstQuery = pm.getQuery(
    lang,
    `
    (const_declaration
      (const_spec
        name: (identifier) @name
        value: (expression_list (interpreted_string_literal) @value)))
    `,
  );
  if (goConstQuery) {
    for (const match of goConstQuery.matches(tree.rootNode)) {
      const nameNode = getCapture(match.captures, "name");
      const valueNode = getCapture(match.captures, "value");
      if (nameNode && valueNode) {
        constants.set(nameNode.text, cleanStringValue(valueNode.text));
      }
    }
  }

  // Ruby: assignment — local var or constant
  const rbQuery = pm.getQuery(
    lang,
    `
    (assignment
      left: (identifier) @name
      right: (string (string_content) @value))

    (assignment
      left: (constant) @name
      right: (string (string_content) @value))
    `,
  );
  if (rbQuery) {
    for (const match of rbQuery.matches(tree.rootNode)) {
      const nameNode = getCapture(match.captures, "name");
      const valueNode = getCapture(match.captures, "value");
      if (nameNode && valueNode) {
        constants.set(nameNode.text, valueNode.text);
      }
    }
  }

  return constants;
}
