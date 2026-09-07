import type Parser from "web-tree-sitter";
import {
  buildConstantMap,
  findAliases,
  getEffectiveClients,
} from "./alias-resolver.js";
import {
  cleanStringValue,
  extractClientName,
  extractIdentifier,
  extractStringFromCaseValue,
  extractStringFromNode,
  getCapture,
  walkNodes,
} from "./ast-helpers.js";
import type { LangFamily } from "./languages.js";
import type { ParserManager } from "./parser-manager.js";
import type { VariantBranch } from "./types.js";

export async function findVariantBranches(
  pm: ParserManager,
  source: string,
  languageId: string,
): Promise<VariantBranch[]> {
  const ready = await pm.ensureReady(languageId);
  if (!ready) {
    return [];
  }

  const { lang, family } = ready;
  const tree = pm.parse(source, lang);
  if (!tree) {
    return [];
  }

  const allClients = getEffectiveClients(pm.config);
  const { clientAliases } = findAliases(pm, lang, tree, family);
  for (const a of clientAliases) {
    allClients.add(a);
  }

  const branches: VariantBranch[] = [];

  // 1. Find flag variable assignments: const variant = posthog.getFeatureFlag("key")
  const assignQuery = pm.getQuery(lang, family.queries.flagAssignments);
  if (assignQuery) {
    const matches = assignQuery.matches(tree.rootNode);
    for (const match of matches) {
      const varNode = getCapture(match.captures, "var_name");
      const clientNode = getCapture(match.captures, "client");
      const methodNode = getCapture(match.captures, "method");
      const keyNode = getCapture(match.captures, "flag_key");
      const assignNode = getCapture(match.captures, "assignment");

      if (!varNode || !clientNode || !methodNode || !keyNode) {
        continue;
      }
      const varClientName = extractClientName(
        clientNode,
        pm.config.detectNestedClients,
      );
      if (!varClientName || !allClients.has(varClientName)) {
        continue;
      }

      const method = methodNode.text;
      if (!family.flagMethods.has(method)) {
        continue;
      }

      const varName = varNode.text;
      const flagKey = cleanStringValue(keyNode.text);
      const afterNode = assignNode ?? varNode;

      // Find if-chains and switches using this variable
      findIfChainsForVar(tree.rootNode, varName, flagKey, afterNode, branches);
      findSwitchForVar(tree.rootNode, varName, flagKey, afterNode, branches);
    }
  }

  // 1a. Resolve flag assignments with identifier arguments: const v = posthog.getFeatureFlag(MY_FLAG)
  const constantMap = buildConstantMap(pm, lang, tree);
  if (constantMap.size > 0) {
    let identAssignQueryStr: string;
    if (family.queries.rubyCaptureCalls !== undefined) {
      // Ruby: assignment with identifier or constant argument
      identAssignQueryStr = `
                  (assignment
                      left: (identifier) @var_name
                      right: (call
                          receiver: (_) @client
                          method: (identifier) @method
                          arguments: (argument_list . (identifier) @flag_id))) @assignment

                  (assignment
                      left: (identifier) @var_name
                      right: (call
                          receiver: (_) @client
                          method: (identifier) @method
                          arguments: (argument_list . (constant) @flag_id))) @assignment`;
    } else if (family.queries.pythonCaptureCalls !== undefined) {
      // Python: assignment with identifier argument
      identAssignQueryStr = `(expression_statement
                  (assignment
                      left: (identifier) @var_name
                      right: (call
                          function: (attribute
                              object: (_) @client
                              attribute: (identifier) @method)
                          arguments: (argument_list . (identifier) @flag_id)))) @assignment`;
    } else {
      // JS: const/let/var with identifier argument
      identAssignQueryStr = `(lexical_declaration
                  (variable_declarator
                      name: (identifier) @var_name
                      value: (call_expression
                          function: (member_expression
                              object: (_) @client
                              property: (property_identifier) @method)
                          arguments: (arguments . (identifier) @flag_id)))) @assignment

              (lexical_declaration
                  (variable_declarator
                      name: (identifier) @var_name
                      value: (await_expression
                          (call_expression
                              function: (member_expression
                                  object: (_) @client
                                  property: (property_identifier) @method)
                              arguments: (arguments . (identifier) @flag_id))))) @assignment

              (variable_declaration
                  (variable_declarator
                      name: (identifier) @var_name
                      value: (call_expression
                          function: (member_expression
                              object: (_) @client
                              property: (property_identifier) @method)
                          arguments: (arguments . (identifier) @flag_id)))) @assignment

              (variable_declaration
                  (variable_declarator
                      name: (identifier) @var_name
                      value: (await_expression
                          (call_expression
                              function: (member_expression
                                  object: (_) @client
                                  property: (property_identifier) @method)
                              arguments: (arguments . (identifier) @flag_id))))) @assignment`;
    }
    const identAssignQuery = pm.getQuery(lang, identAssignQueryStr);
    if (identAssignQuery) {
      const matches = identAssignQuery.matches(tree.rootNode);
      for (const match of matches) {
        const varNode = getCapture(match.captures, "var_name");
        const clientNode = getCapture(match.captures, "client");
        const methodNode = getCapture(match.captures, "method");
        const argNode = getCapture(match.captures, "flag_id");
        const assignNode = getCapture(match.captures, "assignment");

        if (!varNode || !clientNode || !methodNode || !argNode) {
          continue;
        }
        const varClientName = extractClientName(
          clientNode,
          pm.config.detectNestedClients,
        );
        if (!varClientName || !allClients.has(varClientName)) {
          continue;
        }
        if (!family.flagMethods.has(methodNode.text)) {
          continue;
        }

        const resolved = constantMap.get(argNode.text);
        if (!resolved) {
          continue;
        }

        const varName = varNode.text;
        const afterNode = assignNode ?? varNode;
        findIfChainsForVar(
          tree.rootNode,
          varName,
          resolved,
          afterNode,
          branches,
        );
        findSwitchForVar(tree.rootNode, varName, resolved, afterNode, branches);
      }
    }
  }

  // 1b. Find bare function call assignments: const x = useFeatureFlag("key")
  const bareFlagFunctions = new Set([
    ...pm.config.additionalFlagFunctions,
    "useFeatureFlag",
    "useFeatureFlagPayload",
    "useFeatureFlagVariantKey",
  ]);
  if (bareFlagFunctions.size > 0 && family.queries.bareFunctionCalls) {
    const bareAssignQueryStr =
      family.queries.pythonCaptureCalls !== undefined
        ? // Python: bare function assignment
          `(expression_statement
                  (assignment
                      left: (identifier) @var_name
                      right: (call
                          function: (identifier) @func_name
                          arguments: (argument_list . (string (string_content) @flag_key))))) @assignment`
        : // JS: const/let/var bare function assignment
          `(lexical_declaration
                  (variable_declarator
                      name: (identifier) @var_name
                      value: (call_expression
                          function: (identifier) @func_name
                          arguments: (arguments . (string (string_fragment) @flag_key))))) @assignment

              (variable_declaration
                  (variable_declarator
                      name: (identifier) @var_name
                      value: (call_expression
                          function: (identifier) @func_name
                          arguments: (arguments . (string (string_fragment) @flag_key))))) @assignment`;
    const bareAssignQuery = pm.getQuery(lang, bareAssignQueryStr);
    if (bareAssignQuery) {
      const matches = bareAssignQuery.matches(tree.rootNode);
      for (const match of matches) {
        const varNode = getCapture(match.captures, "var_name");
        const funcNode = getCapture(match.captures, "func_name");
        const keyNode = getCapture(match.captures, "flag_key");
        const assignNode = getCapture(match.captures, "assignment");

        if (!varNode || !funcNode || !keyNode) {
          continue;
        }
        if (!bareFlagFunctions.has(funcNode.text)) {
          continue;
        }

        const varName = varNode.text;
        const flagKey = cleanStringValue(keyNode.text);
        const afterNode = assignNode ?? varNode;

        findIfChainsForVar(
          tree.rootNode,
          varName,
          flagKey,
          afterNode,
          branches,
        );
        findSwitchForVar(tree.rootNode, varName, flagKey, afterNode, branches);
      }
    }
  }

  // 2. Find inline flag checks: if (posthog.getFeatureFlag("key") === "variant")
  const detectNested = pm.config.detectNestedClients;
  findInlineFlagIfs(tree.rootNode, allClients, family, branches, detectNested);

  // 3. Find isFeatureEnabled checks: if (posthog.isFeatureEnabled("key"))
  findEnabledIfs(tree.rootNode, allClients, family, branches, detectNested);

  return branches;
}

// ── Variant detection helpers ──

function findIfChainsForVar(
  _root: Parser.SyntaxNode,
  varName: string,
  flagKey: string,
  afterNode: Parser.SyntaxNode,
  branches: VariantBranch[],
): void {
  // Find the containing scope
  const scope = afterNode.parent;
  if (!scope) {
    return;
  }

  let foundAssignment = false;
  for (const child of scope.namedChildren) {
    if (
      child.startIndex >= afterNode.startIndex &&
      child.endIndex >= afterNode.endIndex
    ) {
      foundAssignment = true;
    }
    if (!foundAssignment) {
      continue;
    }
    if (child === afterNode) {
      continue;
    }

    // JS/Go: if_statement, Ruby: if
    if (child.type === "if_statement" || child.type === "if") {
      extractIfChainBranches(child, varName, flagKey, branches);
    }
  }
}

function extractIfChainBranches(
  ifNode: Parser.SyntaxNode,
  varName: string,
  flagKey: string,
  branches: VariantBranch[],
): void {
  const condition = ifNode.childForFieldName("condition");
  const consequence = ifNode.childForFieldName("consequence");
  const alternative = ifNode.childForFieldName("alternative");

  if (!condition || !consequence) {
    return;
  }

  // Only process if the condition actually references the tracked variable
  if (
    !new RegExp(`\\b${varName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(
      condition.text,
    )
  ) {
    return;
  }

  let variant = extractComparison(condition, varName);

  // Truthiness check: if (varName) or if (!varName)
  if (variant === null) {
    const isTruthinessCheck = isTruthinessCheckForVar(condition, varName);
    if (isTruthinessCheck) {
      const negated = isNegated(condition);
      variant = negated ? "false" : "true";
    }
  }

  if (variant === null) {
    return;
  }

  branches.push({
    flagKey,
    variantKey: variant,
    conditionLine: ifNode.startPosition.row,
    startLine: ifNode.startPosition.row,
    endLine: consequence.endPosition.row,
  });

  if (alternative) {
    // Python: elif_clause, Ruby: elsif — has condition, consequence, alternative
    if (alternative.type === "elif_clause" || alternative.type === "elsif") {
      extractIfChainBranches(alternative, varName, flagKey, branches);
    } else if (alternative.type === "else_clause") {
      // JS else_clause may wrap an if_statement (else if). Recurse if so.
      // Otherwise treat as terminal else (Python: body field; JS: statement_block).
      const innerIf = alternative.namedChildren.find(
        (c) => c.type === "if_statement",
      );
      if (innerIf) {
        extractIfChainBranches(innerIf, varName, flagKey, branches);
      } else {
        const body =
          alternative.childForFieldName("body") || alternative.namedChildren[0];
        if (body) {
          const elseVariant =
            variant === "true"
              ? "false"
              : variant === "false"
                ? "true"
                : "else";
          branches.push({
            flagKey,
            variantKey: elseVariant,
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: body.endPosition.row,
          });
        }
      }
    } else if (alternative.type === "if_statement") {
      // Go: else if — alternative is directly an if_statement
      extractIfChainBranches(alternative, varName, flagKey, branches);
    } else if (alternative.type === "block") {
      // Go: else { ... } — alternative is directly a block
      const elseVariant =
        variant === "true" ? "false" : variant === "false" ? "true" : "else";
      branches.push({
        flagKey,
        variantKey: elseVariant,
        conditionLine: alternative.startPosition.row,
        startLine: alternative.startPosition.row,
        endLine: alternative.endPosition.row,
      });
    } else if (alternative.type === "else") {
      // Ruby: else — children are direct statements (no body field)
      const lastChild =
        alternative.namedChildren[alternative.namedChildren.length - 1] ||
        alternative;
      const elseVariant =
        variant === "true" ? "false" : variant === "false" ? "true" : "else";
      branches.push({
        flagKey,
        variantKey: elseVariant,
        conditionLine: alternative.startPosition.row,
        startLine: alternative.startPosition.row,
        endLine: lastChild.endPosition.row,
      });
    }
  }
}

function findSwitchForVar(
  _root: Parser.SyntaxNode,
  varName: string,
  flagKey: string,
  afterNode: Parser.SyntaxNode,
  branches: VariantBranch[],
): void {
  const scope = afterNode.parent;
  if (!scope) {
    return;
  }

  let foundAssignment = false;
  for (const child of scope.namedChildren) {
    if (child.startIndex >= afterNode.startIndex) {
      foundAssignment = true;
    }
    if (!foundAssignment || child === afterNode) {
      continue;
    }

    // JS/TS: switch_statement, Go: expression_switch_statement
    if (
      child.type === "switch_statement" ||
      child.type === "expression_switch_statement"
    ) {
      const value = child.childForFieldName("value");
      if (!value) {
        continue;
      }

      // Check if switch is on our variable
      const switchedVar = extractIdentifier(value);
      if (switchedVar !== varName) {
        continue;
      }

      // JS/TS: cases are inside a 'body' (switch_body) node
      // Go: cases are direct children of the switch node
      const caseContainer = child.childForFieldName("body") || child;

      for (const caseNode of caseContainer.namedChildren) {
        // JS/TS: switch_case, Go: expression_case
        if (
          caseNode.type === "switch_case" ||
          caseNode.type === "expression_case"
        ) {
          const caseValue = caseNode.childForFieldName("value");
          const variantKey = caseValue
            ? extractStringFromCaseValue(caseValue)
            : null;

          // Get the body range: from case line to before next case or end of switch
          const nextSibling = caseNode.nextNamedSibling;
          const endLine = nextSibling
            ? nextSibling.startPosition.row - 1
            : caseContainer.endPosition.row - 1;

          branches.push({
            flagKey,
            variantKey: variantKey || "default",
            conditionLine: caseNode.startPosition.row,
            startLine: caseNode.startPosition.row,
            endLine,
          });
          // JS/TS: switch_default, Go: default_case
        } else if (
          caseNode.type === "switch_default" ||
          caseNode.type === "default_case"
        ) {
          const nextSibling = caseNode.nextNamedSibling;
          const endLine = nextSibling
            ? nextSibling.startPosition.row - 1
            : caseContainer.endPosition.row - 1;

          branches.push({
            flagKey,
            variantKey: "default",
            conditionLine: caseNode.startPosition.row,
            startLine: caseNode.startPosition.row,
            endLine,
          });
        }
      }
    }

    // Ruby: case/when/else
    if (child.type === "case") {
      const value = child.namedChildren[0]; // First named child is the matched expression
      if (!value || value.type === "when") {
        continue;
      } // case without value

      const switchedVar = extractIdentifier(value);
      if (switchedVar !== varName) {
        continue;
      }

      for (const caseChild of child.namedChildren) {
        if (caseChild.type === "when") {
          // when has pattern children and a body (then)
          const patterns = caseChild.namedChildren.filter(
            (c) => c.type === "pattern",
          );
          const body = caseChild.childForFieldName("body");
          const firstPattern = patterns[0];
          const patternStr = firstPattern?.namedChildren[0];
          const variantKey = patternStr
            ? extractStringFromNode(patternStr)
            : null;

          const endLine = body
            ? body.endPosition.row
            : caseChild.endPosition.row;

          branches.push({
            flagKey,
            variantKey: variantKey || "default",
            conditionLine: caseChild.startPosition.row,
            startLine: caseChild.startPosition.row,
            endLine,
          });
        } else if (caseChild.type === "else") {
          const lastChild =
            caseChild.namedChildren[caseChild.namedChildren.length - 1] ||
            caseChild;
          branches.push({
            flagKey,
            variantKey: "default",
            conditionLine: caseChild.startPosition.row,
            startLine: caseChild.startPosition.row,
            endLine: lastChild.endPosition.row,
          });
        }
      }
    }
  }
}

function findInlineFlagIfs(
  root: Parser.SyntaxNode,
  clients: Set<string>,
  family: LangFamily,
  branches: VariantBranch[],
  detectNested: boolean,
): void {
  // Walk all if_statements (JS/Go) and if nodes (Ruby) for inline flag comparisons
  const ifTypes = ["if_statement", "if"];
  for (const ifType of ifTypes) {
    walkNodes(root, ifType, (ifNode) => {
      const condition = ifNode.childForFieldName("condition");
      const consequence = ifNode.childForFieldName("consequence");
      if (!condition || !consequence) {
        return;
      }

      // Look for: getFeatureFlag("key") === "variant"
      const callInfo = extractFlagCallComparison(
        condition,
        clients,
        family,
        detectNested,
      );
      if (!callInfo) {
        return;
      }

      branches.push({
        flagKey: callInfo.flagKey,
        variantKey: callInfo.variant,
        conditionLine: ifNode.startPosition.row,
        startLine: ifNode.startPosition.row,
        endLine: consequence.endPosition.row,
      });

      // Process else chain
      const alternative = ifNode.childForFieldName("alternative");
      if (alternative) {
        // Python: elif_clause, Ruby: elsif
        if (
          alternative.type === "elif_clause" ||
          alternative.type === "elsif"
        ) {
          // walkNodes will find it via recursive walking
        } else if (alternative.type === "else_clause") {
          // JS else_clause may wrap another if_statement (else if).
          // Skip the else label in that case — walkNodes will visit the inner if.
          const innerIf = alternative.namedChildren.find(
            (c) => c.type === "if_statement",
          );
          if (!innerIf) {
            const body =
              alternative.childForFieldName("body") ||
              alternative.namedChildren[0];
            if (body) {
              branches.push({
                flagKey: callInfo.flagKey,
                variantKey: "else",
                conditionLine: alternative.startPosition.row,
                startLine: alternative.startPosition.row,
                endLine: body.endPosition.row,
              });
            }
          }
        } else if (alternative.type === "if_statement") {
          // Go: else if — alternative is directly an if_statement (handled by walkNodes)
        } else if (alternative.type === "block") {
          // Go: else { ... } — alternative is directly a block
          branches.push({
            flagKey: callInfo.flagKey,
            variantKey: "else",
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: alternative.endPosition.row,
          });
        } else if (alternative.type === "else") {
          // Ruby: else — children are direct statements
          const lastChild =
            alternative.namedChildren[alternative.namedChildren.length - 1] ||
            alternative;
          branches.push({
            flagKey: callInfo.flagKey,
            variantKey: "else",
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: lastChild.endPosition.row,
          });
        }
      }
    });
  }

  // Python: also walk elif_clause nodes for inline flag comparisons
  walkNodes(root, "elif_clause", (elifNode) => {
    const condition = elifNode.childForFieldName("condition");
    const consequence = elifNode.childForFieldName("consequence");
    if (!condition || !consequence) {
      return;
    }

    const callInfo = extractFlagCallComparison(
      condition,
      clients,
      family,
      detectNested,
    );
    if (!callInfo) {
      return;
    }

    branches.push({
      flagKey: callInfo.flagKey,
      variantKey: callInfo.variant,
      conditionLine: elifNode.startPosition.row,
      startLine: elifNode.startPosition.row,
      endLine: consequence.endPosition.row,
    });

    const alternative = elifNode.childForFieldName("alternative");
    if (alternative) {
      if (alternative.type === "else_clause") {
        const body =
          alternative.childForFieldName("body") || alternative.namedChildren[0];
        if (body) {
          branches.push({
            flagKey: callInfo.flagKey,
            variantKey: "else",
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: body.endPosition.row,
          });
        }
      }
      // elif_clause chaining: will be handled by walking all elif_clause nodes
    }
  });
}

function findEnabledIfs(
  root: Parser.SyntaxNode,
  clients: Set<string>,
  family: LangFamily,
  branches: VariantBranch[],
  detectNested: boolean,
): void {
  const enabledIfTypes = ["if_statement", "if"];
  for (const ifType of enabledIfTypes) {
    walkNodes(root, ifType, (ifNode) => {
      const condition = ifNode.childForFieldName("condition");
      const consequence = ifNode.childForFieldName("consequence");
      if (!condition || !consequence) {
        return;
      }

      const flagKey = extractEnabledCall(
        condition,
        clients,
        family,
        detectNested,
      );
      if (!flagKey) {
        return;
      }

      // Check for negation
      const negated = isNegated(condition);

      branches.push({
        flagKey,
        variantKey: negated ? "false" : "true",
        conditionLine: ifNode.startPosition.row,
        startLine: ifNode.startPosition.row,
        endLine: consequence.endPosition.row,
      });

      const alternative = ifNode.childForFieldName("alternative");
      if (alternative) {
        // Python: elif_clause, Ruby: elsif
        if (
          alternative.type === "elif_clause" ||
          alternative.type === "elsif"
        ) {
          // Handled by walk below
        } else if (alternative.type === "else_clause") {
          // JS else_clause may wrap another if_statement (else if).
          // Skip the else label in that case — walkNodes will visit the inner if.
          const innerIf = alternative.namedChildren.find(
            (c) => c.type === "if_statement",
          );
          if (!innerIf) {
            const body =
              alternative.childForFieldName("body") ||
              alternative.namedChildren[0];
            if (body) {
              branches.push({
                flagKey,
                variantKey: negated ? "true" : "false",
                conditionLine: alternative.startPosition.row,
                startLine: alternative.startPosition.row,
                endLine: body.endPosition.row,
              });
            }
          }
        } else if (alternative.type === "block") {
          // Go: else { ... } — alternative is directly a block
          branches.push({
            flagKey,
            variantKey: negated ? "true" : "false",
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: alternative.endPosition.row,
          });
        } else if (alternative.type === "else") {
          // Ruby: else — children are direct statements
          const lastChild =
            alternative.namedChildren[alternative.namedChildren.length - 1] ||
            alternative;
          branches.push({
            flagKey,
            variantKey: negated ? "true" : "false",
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: lastChild.endPosition.row,
          });
        }
      }
    });
  }

  // Python/Ruby: also walk elif_clause/elsif nodes for enabled checks
  const elifTypes = ["elif_clause", "elsif"];
  for (const elifType of elifTypes) {
    walkNodes(root, elifType, (elifNode) => {
      const condition = elifNode.childForFieldName("condition");
      const consequence = elifNode.childForFieldName("consequence");
      if (!condition || !consequence) {
        return;
      }

      const flagKey = extractEnabledCall(
        condition,
        clients,
        family,
        detectNested,
      );
      if (!flagKey) {
        return;
      }

      const negated = isNegated(condition);

      branches.push({
        flagKey,
        variantKey: negated ? "false" : "true",
        conditionLine: elifNode.startPosition.row,
        startLine: elifNode.startPosition.row,
        endLine: consequence.endPosition.row,
      });

      const alternative = elifNode.childForFieldName("alternative");
      if (alternative) {
        if (alternative.type === "else_clause") {
          const body =
            alternative.childForFieldName("body") ||
            alternative.namedChildren[0];
          if (body) {
            branches.push({
              flagKey,
              variantKey: negated ? "true" : "false",
              conditionLine: alternative.startPosition.row,
              startLine: alternative.startPosition.row,
              endLine: body.endPosition.row,
            });
          }
        } else if (alternative.type === "else") {
          // Ruby: else
          const lastChild =
            alternative.namedChildren[alternative.namedChildren.length - 1] ||
            alternative;
          branches.push({
            flagKey,
            variantKey: negated ? "true" : "false",
            conditionLine: alternative.startPosition.row,
            startLine: alternative.startPosition.row,
            endLine: lastChild.endPosition.row,
          });
        }
      }
    });
  }
}

// ── Node extraction helpers ──

function extractComparison(
  conditionNode: Parser.SyntaxNode,
  varName: string,
): string | null {
  // Unwrap parenthesized_expression
  let node = conditionNode;
  while (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    node = node.namedChildren[0];
  }

  // JS/Go: binary_expression, Ruby: binary
  if (node.type === "binary_expression" || node.type === "binary") {
    const left = node.childForFieldName("left");
    const right = node.childForFieldName("right");
    const op = node.childForFieldName("operator");

    if (!left || !right) {
      return null;
    }

    const opText = op?.text || "";
    if (
      opText !== "===" &&
      opText !== "==" &&
      opText !== "!==" &&
      opText !== "!="
    ) {
      return null;
    }

    if (left.text === varName) {
      return extractStringFromNode(right);
    }
    if (right.text === varName) {
      return extractStringFromNode(left);
    }
  }

  // Python: comparison_operator (e.g. `flag == "variant"`)
  if (node.type === "comparison_operator") {
    const children = node.namedChildren;
    // comparison_operator has: left_operand, operator(s), right_operand(s)
    // For simple `a == b`, children are [a, b] with operator tokens between
    if (children.length >= 2) {
      const left = children[0];
      const right = children[children.length - 1];
      // Check the operator text between operands
      const fullText = node.text;
      if (fullText.includes("==") || fullText.includes("!=")) {
        if (left.text === varName) {
          return extractStringFromNode(right);
        }
        if (right.text === varName) {
          return extractStringFromNode(left);
        }
      }
    }
  }

  return null;
}

function extractFlagCallComparison(
  conditionNode: Parser.SyntaxNode,
  clients: Set<string>,
  family: LangFamily,
  detectNested: boolean,
): { flagKey: string; variant: string } | null {
  let node = conditionNode;
  while (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    node = node.namedChildren[0];
  }

  let left: Parser.SyntaxNode | null = null;
  let right: Parser.SyntaxNode | null = null;

  // JS/Go: binary_expression, Ruby: binary, Python: comparison_operator
  if (node.type === "binary_expression" || node.type === "binary") {
    left = node.childForFieldName("left");
    right = node.childForFieldName("right");
  } else if (node.type === "comparison_operator") {
    // Python: comparison_operator children are [left_operand, right_operand]
    const children = node.namedChildren;
    if (children.length >= 2) {
      left = children[0];
      right = children[children.length - 1];
    }
  }

  if (!left || !right) {
    return null;
  }

  // Check if left is a posthog.getFeatureFlag("key") call
  const callTypes = new Set(["call_expression", "call"]);
  const callNode = callTypes.has(left.type)
    ? left
    : callTypes.has(right.type)
      ? right
      : null;
  const valueNode = callNode === left ? right : left;
  if (!callNode || !valueNode) {
    return null;
  }

  let obj: Parser.SyntaxNode | null = null;
  let prop: Parser.SyntaxNode | null = null;

  const func = callNode.childForFieldName("function");
  if (
    func &&
    (func.type === "member_expression" ||
      func.type === "attribute" ||
      func.type === "selector_expression")
  ) {
    obj = func.childForFieldName("object") || func.childForFieldName("operand");
    prop =
      func.childForFieldName("property") ||
      func.childForFieldName("attribute") ||
      func.childForFieldName("field");
  } else {
    // Ruby: call has receiver + method as separate fields
    obj = callNode.childForFieldName("receiver");
    prop = callNode.childForFieldName("method");
  }
  if (!obj || !prop) {
    return null;
  }
  const extractedClient = extractClientName(obj, detectNested);
  if (!extractedClient || !clients.has(extractedClient)) {
    return null;
  }

  const method = prop.text;
  // Only match getFeatureFlag-like methods (not isFeatureEnabled which returns bool)
  const flagGetters = new Set(
    [...family.flagMethods].filter(
      (m) =>
        m.toLowerCase().includes("get") || m.toLowerCase().includes("flag"),
    ),
  );
  if (!flagGetters.has(method)) {
    return null;
  }

  const args = callNode.childForFieldName("arguments");
  if (!args) {
    return null;
  }
  const firstArg = args.namedChildren[0];
  if (!firstArg) {
    return null;
  }

  const flagKey = extractStringFromNode(firstArg);
  const variant = extractStringFromNode(valueNode);
  if (!flagKey || !variant) {
    return null;
  }

  return { flagKey, variant };
}

function extractEnabledCall(
  conditionNode: Parser.SyntaxNode,
  clients: Set<string>,
  family: LangFamily,
  detectNested: boolean,
): string | null {
  let node = conditionNode;
  // Unwrap parenthesized_expression and unary ! (negation)
  while (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    node = node.namedChildren[0];
  }
  // JS: unary_expression, Python: not_operator, Ruby: unary
  if (
    node.type === "unary_expression" ||
    node.type === "not_operator" ||
    node.type === "unary"
  ) {
    const operand =
      node.childForFieldName("operand") ||
      node.namedChildren[node.namedChildren.length - 1];
    if (operand) {
      node = operand;
    }
  }
  while (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    node = node.namedChildren[0];
  }

  if (node.type !== "call_expression" && node.type !== "call") {
    return null;
  }

  let clientName: string | undefined;
  let methodName: string | undefined;

  const func = node.childForFieldName("function");
  if (func) {
    if (
      func.type === "member_expression" ||
      func.type === "attribute" ||
      func.type === "selector_expression"
    ) {
      const obj =
        func.childForFieldName("object") || func.childForFieldName("operand");
      const prop =
        func.childForFieldName("property") ||
        func.childForFieldName("attribute") ||
        func.childForFieldName("field");
      clientName = obj
        ? (extractClientName(obj, detectNested) ?? undefined)
        : undefined;
      methodName = prop?.text;
    }
  } else {
    // Ruby: call has receiver + method as separate fields
    const receiver = node.childForFieldName("receiver");
    const method = node.childForFieldName("method");
    if (receiver && method) {
      clientName = extractClientName(receiver, detectNested) ?? undefined;
      methodName = method.text;
    }
  }

  if (!clientName || !methodName || !clients.has(clientName)) {
    return null;
  }

  // Match isFeatureEnabled-like methods
  const enabledMethods = new Set(
    [...family.flagMethods].filter(
      (m) =>
        m.toLowerCase().includes("enabled") ||
        m.toLowerCase().includes("is_feature"),
    ),
  );
  if (!enabledMethods.has(methodName)) {
    return null;
  }

  const args = node.childForFieldName("arguments");
  if (!args) {
    return null;
  }
  const firstArg = args.namedChildren[0];
  return firstArg ? extractStringFromNode(firstArg) : null;
}

function isNegated(conditionNode: Parser.SyntaxNode): boolean {
  let node = conditionNode;
  while (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    node = node.namedChildren[0];
  }
  // JS: unary_expression, Python: not_operator, Ruby: unary
  return (
    (node.type === "unary_expression" && node.text.startsWith("!")) ||
    node.type === "not_operator" ||
    (node.type === "unary" && node.text.startsWith("!"))
  );
}

/** Check if a condition is a simple truthiness check on a variable: `if (varName)` or `if (!varName)` */
function isTruthinessCheckForVar(
  conditionNode: Parser.SyntaxNode,
  varName: string,
): boolean {
  let node = conditionNode;
  while (
    node.type === "parenthesized_expression" &&
    node.namedChildren.length === 1
  ) {
    node = node.namedChildren[0];
  }
  // if (varName)
  if (node.type === "identifier" && node.text === varName) {
    return true;
  }
  // if (!varName) — JS: unary_expression, Python: not_operator, Ruby: unary
  if (
    (node.type === "unary_expression" ||
      node.type === "not_operator" ||
      node.type === "unary") &&
    node.namedChildren.length > 0
  ) {
    let inner = node.namedChildren[node.namedChildren.length - 1];
    while (
      inner.type === "parenthesized_expression" &&
      inner.namedChildren.length === 1
    ) {
      inner = inner.namedChildren[0];
    }
    if (inner.type === "identifier" && inner.text === varName) {
      return true;
    }
  }
  return false;
}

/** Build a map of const/let/var identifier → string value from the file */
