import type Parser from "web-tree-sitter";
import {
  buildConstantMap,
  findAliases,
  getEffectiveClients,
} from "./alias-resolver.js";
import {
  cleanStringValue,
  extractClientName,
  extractParams,
  getCapture,
  isInsideJsx,
} from "./ast-helpers.js";
import type { ParserManager } from "./parser-manager.js";
import type {
  FlagAssignment,
  FunctionInfo,
  LocalWrapper,
  ParseContext,
  PostHogCall,
  PostHogInitCall,
} from "./types.js";

const POSTHOG_CLASS_NAMES = new Set(["PostHog", "Posthog"]);
const GO_CONSTRUCTOR_NAMES = new Set(["New", "NewWithConfig"]);

export async function findPostHogCalls(
  pm: ParserManager,
  source: string,
  languageId: string,
  context?: ParseContext,
): Promise<PostHogCall[]> {
  const ready = await pm.ensureReady(languageId);
  if (!ready) {
    return [];
  }

  const { lang, family } = ready;
  const tree = pm.parse(source, lang);
  if (!tree) {
    return [];
  }

  const calls: PostHogCall[] = [];
  const seen = new Set<string>();
  const allClients = getEffectiveClients(pm.config);

  // Resolve aliases
  const { clientAliases, destructuredCapture, destructuredFlag } = findAliases(
    pm,
    lang,
    tree,
    family,
  );
  for (const a of clientAliases) {
    allClients.add(a);
  }

  // Direct method calls: posthog.capture("event")
  const callQuery = pm.getQuery(lang, family.queries.postHogCalls);
  if (callQuery) {
    const matches = callQuery.matches(tree.rootNode);
    for (const match of matches) {
      const clientNode = getCapture(match.captures, "client");
      const methodNode = getCapture(match.captures, "method");
      const keyNode = getCapture(match.captures, "key");
      const callNode = getCapture(match.captures, "call");

      if (!clientNode || !methodNode || !keyNode) {
        continue;
      }

      const clientName = extractClientName(
        clientNode,
        pm.config.detectNestedClients,
      );
      const method = methodNode.text;

      if (!clientName || !allClients.has(clientName)) {
        continue;
      }
      if (!family.allMethods.has(method)) {
        continue;
      }

      // For Python, skip capture in the generic query — the first arg is distinct_id, not the event.
      // Python capture is handled separately by the pythonCaptureCalls query.
      if (
        family.queries.pythonCaptureCalls &&
        family.captureMethods.has(method)
      ) {
        continue;
      }

      // For Ruby, skip capture — event is in the `event:` keyword arg, not the first positional arg.
      // Ruby capture is handled separately by the rubyCaptureCalls query.
      if (
        family.queries.rubyCaptureCalls &&
        family.captureMethods.has(method)
      ) {
        continue;
      }

      calls.push({
        method,
        key: cleanStringValue(keyNode.text),
        line: keyNode.startPosition.row,
        keyStartCol: keyNode.startPosition.column,
        keyEndCol: keyNode.endPosition.column,
        inJsx: callNode ? isInsideJsx(callNode) : undefined,
      });
    }
  }

  // Go struct-based calls: client.Enqueue(posthog.Capture{Event: "purchase"})
  // and client.GetFeatureFlag(posthog.FeatureFlagPayload{Key: "my-flag"})
  if (family.queries.goStructCalls) {
    const structQuery = pm.getQuery(lang, family.queries.goStructCalls);
    if (structQuery) {
      for (const match of structQuery.matches(tree.rootNode)) {
        const clientNode = getCapture(match.captures, "client");
        const methodNode = getCapture(match.captures, "method");
        const fieldNameNode = getCapture(match.captures, "field_name");
        const keyNode = getCapture(match.captures, "key");
        if (!clientNode || !methodNode || !fieldNameNode || !keyNode) {
          continue;
        }

        const clientName = extractClientName(
          clientNode,
          pm.config.detectNestedClients,
        );
        const method = methodNode.text;
        const fieldName = fieldNameNode.text;
        if (!clientName || !allClients.has(clientName)) {
          continue;
        }

        // For Enqueue(posthog.Capture{Event: "..."}), method is "Enqueue" and we want Event field
        // For GetFeatureFlag(posthog.FeatureFlagPayload{Key: "..."}), we want Key field
        const isCapture = method === "Enqueue" && fieldName === "Event";
        const isFlag = family.flagMethods.has(method) && fieldName === "Key";
        if (!isCapture && !isFlag) {
          continue;
        }

        const effectiveMethod = isCapture ? "capture" : method;
        const key = cleanStringValue(keyNode.text);
        const line = keyNode.startPosition.row;
        const dedupKey = `${line}:${key}`;
        if (seen.has(dedupKey)) {
          continue;
        }
        seen.add(dedupKey);

        calls.push({
          method: effectiveMethod,
          key,
          line,
          keyStartCol: keyNode.startPosition.column,
          keyEndCol: keyNode.endPosition.column,
        });
      }
    }
  }

  // Node SDK capture calls: client.capture({ event: 'purchase', ... })
  const nodeCaptureQuery = pm.getQuery(lang, family.queries.nodeCaptureCalls);
  if (nodeCaptureQuery) {
    const matches = nodeCaptureQuery.matches(tree.rootNode);
    for (const match of matches) {
      const clientNode = getCapture(match.captures, "client");
      const methodNode = getCapture(match.captures, "method");
      const propNameNode = getCapture(match.captures, "prop_name");
      const keyNode = getCapture(match.captures, "key");
      const callNode = getCapture(match.captures, "call");

      if (!clientNode || !methodNode || !propNameNode || !keyNode) {
        continue;
      }

      const clientName = extractClientName(
        clientNode,
        pm.config.detectNestedClients,
      );
      const method = methodNode.text;

      if (!clientName || !allClients.has(clientName)) {
        continue;
      }
      if (method !== "capture") {
        continue;
      }
      if (propNameNode.text !== "event") {
        continue;
      }

      calls.push({
        method,
        key: cleanStringValue(keyNode.text),
        line: keyNode.startPosition.row,
        keyStartCol: keyNode.startPosition.column,
        keyEndCol: keyNode.endPosition.column,
        inJsx: callNode ? isInsideJsx(callNode) : undefined,
      });
    }
  }

  // Python capture: posthog.capture(distinct_id, 'event_name', ...)
  // Event is the 2nd positional arg, or the `event` keyword argument
  if (family.queries.pythonCaptureCalls) {
    const pyCaptureQuery = pm.getQuery(lang, family.queries.pythonCaptureCalls);
    if (pyCaptureQuery) {
      const matches = pyCaptureQuery.matches(tree.rootNode);
      for (const match of matches) {
        const clientNode = getCapture(match.captures, "client");
        const methodNode = getCapture(match.captures, "method");
        const keyNode = getCapture(match.captures, "key");
        const kwargNameNode = getCapture(match.captures, "kwarg_name");

        if (!clientNode || !methodNode || !keyNode) {
          continue;
        }

        const clientName = extractClientName(
          clientNode,
          pm.config.detectNestedClients,
        );
        const method = methodNode.text;

        if (!clientName || !allClients.has(clientName)) {
          continue;
        }
        if (method !== "capture") {
          continue;
        }

        // For keyword argument form, only match event=
        if (kwargNameNode && kwargNameNode.text !== "event") {
          continue;
        }

        const key = cleanStringValue(keyNode.text);
        const line = keyNode.startPosition.row;
        const dedupKey = `${line}:${key}`;
        if (seen.has(dedupKey)) {
          continue;
        }
        seen.add(dedupKey);

        calls.push({
          method,
          key,
          line,
          keyStartCol: keyNode.startPosition.column,
          keyEndCol: keyNode.endPosition.column,
        });
      }
    }
  }

  // Ruby capture: client.capture(distinct_id: 'user', event: 'purchase')
  // Event name is in the `event:` keyword argument (hash_key_symbol)
  if (family.queries.rubyCaptureCalls) {
    const rbCaptureQuery = pm.getQuery(lang, family.queries.rubyCaptureCalls);
    if (rbCaptureQuery) {
      const matches = rbCaptureQuery.matches(tree.rootNode);
      for (const match of matches) {
        const clientNode = getCapture(match.captures, "client");
        const methodNode = getCapture(match.captures, "method");
        const keyNode = getCapture(match.captures, "key");
        const kwargNameNode = getCapture(match.captures, "kwarg_name");

        if (!clientNode || !methodNode || !keyNode || !kwargNameNode) {
          continue;
        }

        const clientName = extractClientName(
          clientNode,
          pm.config.detectNestedClients,
        );
        const method = methodNode.text;

        if (!clientName || !allClients.has(clientName)) {
          continue;
        }
        if (method !== "capture") {
          continue;
        }
        if (kwargNameNode.text !== "event") {
          continue;
        }

        const key = cleanStringValue(keyNode.text);
        const line = keyNode.startPosition.row;
        const dedupKey = `${line}:${key}`;
        if (seen.has(dedupKey)) {
          continue;
        }
        seen.add(dedupKey);

        calls.push({
          method,
          key,
          line,
          keyStartCol: keyNode.startPosition.column,
          keyEndCol: keyNode.endPosition.column,
        });
      }
    }
  }

  // Bare function calls from destructured methods: capture("event")
  if (destructuredCapture.size > 0 || destructuredFlag.size > 0) {
    const bareQuery = pm.getQuery(lang, family.queries.bareFunctionCalls);
    if (bareQuery) {
      const matches = bareQuery.matches(tree.rootNode);
      for (const match of matches) {
        const funcNode = getCapture(match.captures, "func_name");
        const keyNode = getCapture(match.captures, "key");
        const callNode = getCapture(match.captures, "call");
        if (!funcNode || !keyNode) {
          continue;
        }

        const name = funcNode.text;
        if (destructuredCapture.has(name) || destructuredFlag.has(name)) {
          calls.push({
            method: name,
            key: cleanStringValue(keyNode.text),
            line: keyNode.startPosition.row,
            keyStartCol: keyNode.startPosition.column,
            keyEndCol: keyNode.endPosition.column,
            inJsx: callNode ? isInsideJsx(callNode) : undefined,
          });
        }
      }
    }
  }

  // Additional flag functions: useFeatureFlag("key"), etc.
  if (
    pm.config.additionalFlagFunctions.length > 0 &&
    family.queries.bareFunctionCalls
  ) {
    const additionalFlagFuncs = new Set(pm.config.additionalFlagFunctions);
    const bareQuery = pm.getQuery(lang, family.queries.bareFunctionCalls);
    if (bareQuery) {
      const matches = bareQuery.matches(tree.rootNode);
      for (const match of matches) {
        const funcNode = getCapture(match.captures, "func_name");
        const keyNode = getCapture(match.captures, "key");
        const callNode = getCapture(match.captures, "call");
        if (!funcNode || !keyNode) {
          continue;
        }

        if (additionalFlagFuncs.has(funcNode.text)) {
          calls.push({
            method: funcNode.text,
            key: cleanStringValue(keyNode.text),
            line: keyNode.startPosition.row,
            keyStartCol: keyNode.startPosition.column,
            keyEndCol: keyNode.endPosition.column,
            inJsx: callNode ? isInsideJsx(callNode) : undefined,
          });
        }
      }
    }
  }

  // Resolve calls with identifier first argument: posthog.capture(MY_CONST) / posthog.getFeatureFlag(FLAG_KEY)
  const constantMap = buildConstantMap(pm, lang, tree);
  if (constantMap.size > 0) {
    const identArgQuery = pm.getQuery(lang, family.queries.identifierArgCalls);
    if (identArgQuery) {
      const identMatches = identArgQuery.matches(tree.rootNode);
      for (const match of identMatches) {
        const clientNode = getCapture(match.captures, "client");
        const methodNode = getCapture(match.captures, "method");
        const argNode = getCapture(match.captures, "arg_id");
        const callNode = getCapture(match.captures, "call");
        if (!clientNode || !methodNode || !argNode) {
          continue;
        }

        const clientName = extractClientName(
          clientNode,
          pm.config.detectNestedClients,
        );
        const method = methodNode.text;
        if (!clientName || !allClients.has(clientName)) {
          continue;
        }
        if (!family.allMethods.has(method)) {
          continue;
        }

        const resolved = constantMap.get(argNode.text);
        if (!resolved) {
          continue;
        }

        const line = argNode.startPosition.row;
        const dedupKey = `${line}:${resolved}`;
        if (seen.has(dedupKey)) {
          continue;
        }
        seen.add(dedupKey);

        calls.push({
          method,
          key: resolved,
          line,
          keyStartCol: argNode.startPosition.column,
          keyEndCol: argNode.endPosition.column,
          inJsx: callNode ? isInsideJsx(callNode) : undefined,
        });
      }
    }
  }

  // Detect dynamic capture calls (non-string first argument)
  const matchedLines = new Set(calls.map((c) => c.line));
  const dynamicQuery = pm.getQuery(lang, family.queries.dynamicCalls);
  if (dynamicQuery) {
    const matches = dynamicQuery.matches(tree.rootNode);
    for (const match of matches) {
      const clientNode = getCapture(match.captures, "client");
      const methodNode = getCapture(match.captures, "method");
      const firstArgNode = getCapture(match.captures, "first_arg");
      const callNode = getCapture(match.captures, "call");
      if (!clientNode || !methodNode || !firstArgNode) {
        continue;
      }

      const clientName = extractClientName(
        clientNode,
        pm.config.detectNestedClients,
      );
      const method = methodNode.text;
      if (!clientName || !allClients.has(clientName)) {
        continue;
      }
      if (!family.captureMethods.has(method)) {
        continue;
      }

      const line = firstArgNode.startPosition.row;
      if (matchedLines.has(line)) {
        continue;
      } // already matched with a string key

      calls.push({
        method,
        key: "",
        line,
        keyStartCol: firstArgNode.startPosition.column,
        keyEndCol: firstArgNode.endPosition.column,
        dynamic: true,
        inJsx: callNode ? isInsideJsx(callNode) : undefined,
      });
      matchedLines.add(line);
    }
  }

  if (context?.wrappersByLocalName?.size) {
    synthesizeBareWrapperCalls(
      pm,
      lang,
      tree,
      languageId,
      context.wrappersByLocalName,
      constantMap,
      calls,
      matchedLines,
    );
  }

  if (context?.namespaceWrappers?.size) {
    synthesizeNamespaceWrapperCalls(
      pm,
      lang,
      tree,
      languageId,
      context.namespaceWrappers,
      constantMap,
      calls,
      matchedLines,
    );
  }

  return calls;
}

const WRAPPER_BARE_CALL_QUERIES: Record<string, string | undefined> = {
  javascript: `(call_expression function: (identifier) @func_name arguments: (arguments) @args) @call`,
  javascriptreact: `(call_expression function: (identifier) @func_name arguments: (arguments) @args) @call`,
  typescript: `(call_expression function: (identifier) @func_name arguments: (arguments) @args) @call`,
  typescriptreact: `(call_expression function: (identifier) @func_name arguments: (arguments) @args) @call`,
  python: `(call function: (identifier) @func_name arguments: (argument_list) @args) @call`,
};

const WRAPPER_NAMESPACE_CALL_QUERIES: Record<string, string | undefined> = {
  javascript: `(call_expression function: (member_expression object: (identifier) @ns property: (property_identifier) @method) arguments: (arguments) @args) @call`,
  javascriptreact: `(call_expression function: (member_expression object: (identifier) @ns property: (property_identifier) @method) arguments: (arguments) @args) @call`,
  typescript: `(call_expression function: (member_expression object: (identifier) @ns property: (property_identifier) @method) arguments: (arguments) @args) @call`,
  typescriptreact: `(call_expression function: (member_expression object: (identifier) @ns property: (property_identifier) @method) arguments: (arguments) @args) @call`,
  python: `(call function: (attribute object: (identifier) @ns attribute: (identifier) @method) arguments: (argument_list) @args) @call`,
};

function synthesizeBareWrapperCalls(
  pm: ParserManager,
  lang: Parser.Language,
  tree: Parser.Tree,
  languageId: string,
  wrappers: Map<string, LocalWrapper>,
  constantMap: Map<string, string>,
  calls: PostHogCall[],
  matchedLines: Set<number>,
): void {
  const queryStr = WRAPPER_BARE_CALL_QUERIES[languageId];
  if (!queryStr) return;
  const query = pm.getQuery(lang, queryStr);
  if (!query) return;

  for (const match of query.matches(tree.rootNode)) {
    const funcNode = getCapture(match.captures, "func_name");
    const argsNode = getCapture(match.captures, "args");
    const callNode = getCapture(match.captures, "call");
    if (!funcNode || !argsNode) continue;
    const wrapper = wrappers.get(funcNode.text);
    if (!wrapper) continue;
    pushWrapperCall(
      wrapper,
      funcNode,
      argsNode,
      callNode,
      constantMap,
      calls,
      matchedLines,
    );
  }
}

function synthesizeNamespaceWrapperCalls(
  pm: ParserManager,
  lang: Parser.Language,
  tree: Parser.Tree,
  languageId: string,
  namespaceWrappers: Map<string, Map<string, LocalWrapper>>,
  constantMap: Map<string, string>,
  calls: PostHogCall[],
  matchedLines: Set<number>,
): void {
  const queryStr = WRAPPER_NAMESPACE_CALL_QUERIES[languageId];
  if (!queryStr) return;
  const query = pm.getQuery(lang, queryStr);
  if (!query) return;

  for (const match of query.matches(tree.rootNode)) {
    const nsNode = getCapture(match.captures, "ns");
    const methodNode = getCapture(match.captures, "method");
    const argsNode = getCapture(match.captures, "args");
    const callNode = getCapture(match.captures, "call");
    if (!nsNode || !methodNode || !argsNode) continue;
    const nsWrappers = namespaceWrappers.get(nsNode.text);
    if (!nsWrappers) continue;
    const wrapper = nsWrappers.get(methodNode.text);
    if (!wrapper) continue;
    pushWrapperCall(
      wrapper,
      methodNode,
      argsNode,
      callNode,
      constantMap,
      calls,
      matchedLines,
    );
  }
}

function pushWrapperCall(
  wrapper: LocalWrapper,
  callerNode: Parser.SyntaxNode,
  argsNode: Parser.SyntaxNode,
  callNode: Parser.SyntaxNode | null,
  constantMap: Map<string, string>,
  calls: PostHogCall[],
  matchedLines: Set<number>,
): void {
  let line = callerNode.startPosition.row;
  let keyStartCol = callerNode.startPosition.column;
  let keyEndCol = callerNode.endPosition.column;
  let key = "";
  let dynamic = false;

  if (wrapper.classification.kind === "fixed-key") {
    key = wrapper.classification.key;
  } else {
    const positional = argsNode.namedChildren.filter(
      (c) => c.type !== "comment" && c.type !== "keyword_argument",
    );
    const arg = positional[wrapper.classification.paramIndex];
    if (!arg) return;
    line = arg.startPosition.row;
    keyStartCol = arg.startPosition.column;
    keyEndCol = arg.endPosition.column;

    if (arg.type === "string") {
      const fragment = arg.namedChildren.find(
        (c) => c.type === "string_fragment" || c.type === "string_content",
      );
      if (fragment) {
        key = fragment.text;
      } else {
        dynamic = true;
      }
    } else if (arg.type === "template_string") {
      const fragments = arg.namedChildren.filter(
        (c) => c.type === "string_fragment",
      );
      const hasInterp = arg.namedChildren.some(
        (c) => c.type === "template_substitution",
      );
      if (!hasInterp && fragments.length === 1) {
        key = fragments[0].text;
      } else {
        dynamic = true;
      }
    } else if (arg.type === "interpreted_string_literal") {
      key = arg.text.slice(1, -1);
    } else if (arg.type === "identifier") {
      const resolved = constantMap.get(arg.text);
      if (resolved) {
        key = resolved;
      } else {
        dynamic = true;
      }
    } else {
      dynamic = true;
    }
  }

  if (matchedLines.has(line) && dynamic) {
    // Direct PostHog call already annotated this line — don't overwrite with opaque wrapper data.
    return;
  }

  calls.push({
    method: wrapper.posthogMethod,
    key,
    line,
    keyStartCol,
    keyEndCol,
    dynamic: dynamic ? true : undefined,
    viaWrapper: wrapper.name,
    inJsx: callNode ? isInsideJsx(callNode) : undefined,
  });
  matchedLines.add(line);
}

export async function findInitCalls(
  pm: ParserManager,
  source: string,
  languageId: string,
): Promise<PostHogInitCall[]> {
  const ready = await pm.ensureReady(languageId);
  if (!ready) {
    return [];
  }

  const { lang } = ready;
  const tree = pm.parse(source, lang);
  if (!tree) {
    return [];
  }

  const allClients = getEffectiveClients(pm.config);
  const results: PostHogInitCall[] = [];
  const seenLines = new Set<number>();

  // Pattern 1: posthog.init('token', { ... })
  const initQueryStr = `
            (call_expression
                function: (member_expression
                    object: (_) @client
                    property: (property_identifier) @method)
                arguments: (arguments
                    (string (string_fragment) @token)
                    (object)? @config)) @call
        `;

  const initQuery = pm.getQuery(lang, initQueryStr);
  if (initQuery) {
    for (const match of initQuery.matches(tree.rootNode)) {
      const clientNode = getCapture(match.captures, "client");
      const methodNode = getCapture(match.captures, "method");
      const tokenNode = getCapture(match.captures, "token");
      const configNode = getCapture(match.captures, "config");

      if (!clientNode || !methodNode || !tokenNode) {
        continue;
      }
      if (methodNode.text !== "init") {
        continue;
      }

      const clientName = extractClientName(
        clientNode,
        pm.config.detectNestedClients,
      );
      if (!clientName || !allClients.has(clientName)) {
        continue;
      }

      results.push(buildInitCall(tokenNode, configNode ?? undefined));
    }
  }

  // Pattern 2: new PostHog('token', { ... }) — Node SDK
  const constructorQueryStr = `
            (new_expression
                constructor: (identifier) @class_name
                arguments: (arguments
                    (string (string_fragment) @token)
                    (object)? @config)) @call
        `;

  const ctorQuery = pm.getQuery(lang, constructorQueryStr);
  if (ctorQuery) {
    for (const match of ctorQuery.matches(tree.rootNode)) {
      const classNode = getCapture(match.captures, "class_name");
      const tokenNode = getCapture(match.captures, "token");
      const configNode = getCapture(match.captures, "config");

      if (!classNode || !tokenNode) {
        continue;
      }
      if (!POSTHOG_CLASS_NAMES.has(classNode.text)) {
        continue;
      }

      results.push(buildInitCall(tokenNode, configNode ?? undefined));
    }
  }

  // Pattern 3a: Posthog('phc_token', host='...') — positional token
  const pyCtorQueryStr = `
            (call
                function: (identifier) @class_name
                arguments: (argument_list
                    (string (string_content) @token))) @call
        `;

  // Pattern 3b: Posthog(api_key='phc_token', host='...') — keyword token
  const pyCtorKwQueryStr = `
            (call
                function: (identifier) @class_name
                arguments: (argument_list
                    (keyword_argument
                        name: (identifier) @kw_name
                        value: (string (string_content) @token)))) @call
        `;

  const pyCtorKwQuery = pm.getQuery(lang, pyCtorKwQueryStr);
  if (pyCtorKwQuery) {
    for (const match of pyCtorKwQuery.matches(tree.rootNode)) {
      const classNode = getCapture(match.captures, "class_name");
      const kwNameNode = getCapture(match.captures, "kw_name");
      const tokenNode = getCapture(match.captures, "token");

      if (!classNode || !kwNameNode || !tokenNode) {
        continue;
      }
      if (!POSTHOG_CLASS_NAMES.has(classNode.text)) {
        continue;
      }
      if (
        kwNameNode.text !== "api_key" &&
        kwNameNode.text !== "project_api_key"
      ) {
        continue;
      }

      // Check we didn't already match this call via positional pattern
      const line = tokenNode.startPosition.row;
      if (seenLines.has(line)) {
        continue;
      }
      seenLines.add(line);

      // Extract other keyword args for config
      const callNode = getCapture(match.captures, "call");
      const configProperties = new Map<string, string>();
      let apiHost: string | null = null;

      if (callNode) {
        const argsNode = callNode.childForFieldName("arguments");
        if (argsNode) {
          for (const child of argsNode.namedChildren) {
            if (child.type === "keyword_argument") {
              const nameNode = child.childForFieldName("name");
              const valueNode = child.childForFieldName("value");
              if (
                nameNode &&
                valueNode &&
                nameNode.text !== "api_key" &&
                nameNode.text !== "project_api_key"
              ) {
                const key = nameNode.text;
                let value = valueNode.text;
                if (valueNode.type === "string") {
                  const content = valueNode.namedChildren.find(
                    (c) => c.type === "string_content",
                  );
                  if (content) {
                    value = content.text;
                  }
                }
                configProperties.set(key, value);
                if (key === "host" || key === "api_host") {
                  apiHost = value;
                }
              }
            }
          }
        }
      }

      results.push({
        token: cleanStringValue(tokenNode.text),
        tokenLine: tokenNode.startPosition.row,
        tokenStartCol: tokenNode.startPosition.column,
        tokenEndCol: tokenNode.endPosition.column,
        apiHost,
        configProperties,
      });
    }
  }

  const pyCtorQuery = pm.getQuery(lang, pyCtorQueryStr);
  if (pyCtorQuery) {
    for (const match of pyCtorQuery.matches(tree.rootNode)) {
      const classNode = getCapture(match.captures, "class_name");
      const tokenNode = getCapture(match.captures, "token");

      if (!classNode || !tokenNode) {
        continue;
      }
      if (!POSTHOG_CLASS_NAMES.has(classNode.text)) {
        continue;
      }

      // Extract keyword arguments for config
      const callNode = getCapture(match.captures, "call");
      const configProperties = new Map<string, string>();
      let apiHost: string | null = null;

      if (callNode) {
        const argsNode = callNode.childForFieldName("arguments");
        if (argsNode) {
          for (const child of argsNode.namedChildren) {
            if (child.type === "keyword_argument") {
              const nameNode = child.childForFieldName("name");
              const valueNode = child.childForFieldName("value");
              if (nameNode && valueNode) {
                const key = nameNode.text;
                let value = valueNode.text;
                if (valueNode.type === "string") {
                  const content = valueNode.namedChildren.find(
                    (c) => c.type === "string_content",
                  );
                  if (content) {
                    value = content.text;
                  }
                }
                configProperties.set(key, value);
                if (key === "host" || key === "api_host") {
                  apiHost = value;
                }
              }
            }
          }
        }
      }

      results.push({
        token: cleanStringValue(tokenNode.text),
        tokenLine: tokenNode.startPosition.row,
        tokenStartCol: tokenNode.startPosition.column,
        tokenEndCol: tokenNode.endPosition.column,
        apiHost,
        configProperties,
      });
    }
  }

  // Pattern 4: Go — posthog.New("phc_token") or posthog.NewWithConfig("phc_token", posthog.Config{Endpoint: "..."})
  const goCtorQueryStr = `
            (call_expression
                function: (selector_expression
                    operand: (identifier) @pkg_name
                    field: (field_identifier) @func_name)
                arguments: (argument_list
                    (interpreted_string_literal) @token)) @call
        `;

  const goCtorQuery = pm.getQuery(lang, goCtorQueryStr);
  if (goCtorQuery) {
    for (const match of goCtorQuery.matches(tree.rootNode)) {
      const pkgNode = getCapture(match.captures, "pkg_name");
      const funcNode = getCapture(match.captures, "func_name");
      const tokenNode = getCapture(match.captures, "token");

      if (!pkgNode || !funcNode || !tokenNode) {
        continue;
      }
      if (pkgNode.text !== "posthog") {
        continue;
      }
      if (!GO_CONSTRUCTOR_NAMES.has(funcNode.text)) {
        continue;
      }

      const token = cleanStringValue(tokenNode.text);
      const line = tokenNode.startPosition.row;
      if (seenLines.has(line)) {
        continue;
      }
      seenLines.add(line);

      // Try to extract Endpoint from Config struct literal
      const configProperties = new Map<string, string>();
      let apiHost: string | null = null;

      const callNode = getCapture(match.captures, "call");
      if (callNode) {
        const argsNode = callNode.childForFieldName("arguments");
        if (argsNode) {
          for (const arg of argsNode.namedChildren) {
            if (arg.type === "composite_literal") {
              const body = arg.childForFieldName("body");
              if (body) {
                for (const elem of body.namedChildren) {
                  if (elem.type === "keyed_element") {
                    const children = elem.namedChildren;
                    if (children.length >= 2) {
                      const keyElem = children[0];
                      const valElem = children[1];
                      const keyId =
                        keyElem.type === "literal_element"
                          ? keyElem.namedChildren[0]?.text || keyElem.text
                          : keyElem.text;
                      const valText = cleanStringValue(valElem.text);
                      if (keyId) {
                        configProperties.set(keyId, valText);
                        if (keyId === "Endpoint" || keyId === "Host") {
                          apiHost = valText;
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }

      results.push({
        token,
        tokenLine: tokenNode.startPosition.row,
        tokenStartCol: tokenNode.startPosition.column,
        tokenEndCol: tokenNode.endPosition.column,
        apiHost,
        configProperties,
      });
    }
  }

  // Pattern 5: Ruby — PostHog::Client.new(api_key: 'phc_token', host: '...')
  const rbCtorQueryStr = `
            (call
                receiver: (scope_resolution
                    scope: (constant) @scope_name
                    name: (constant) @class_name)
                method: (identifier) @method_name
                arguments: (argument_list
                    (pair
                        (hash_key_symbol) @kw_name
                        (string (string_content) @token)))) @call
        `;
  const rbCtorQuery = pm.getQuery(lang, rbCtorQueryStr);
  if (rbCtorQuery) {
    for (const match of rbCtorQuery.matches(tree.rootNode)) {
      const scopeNode = getCapture(match.captures, "scope_name");
      const classNode = getCapture(match.captures, "class_name");
      const methodNode = getCapture(match.captures, "method_name");
      const kwNameNode = getCapture(match.captures, "kw_name");
      const tokenNode = getCapture(match.captures, "token");

      if (
        !scopeNode ||
        !classNode ||
        !methodNode ||
        !kwNameNode ||
        !tokenNode
      ) {
        continue;
      }
      if (!POSTHOG_CLASS_NAMES.has(scopeNode.text)) {
        continue;
      }
      if (classNode.text !== "Client") {
        continue;
      }
      if (methodNode.text !== "new") {
        continue;
      }
      if (kwNameNode.text !== "api_key") {
        continue;
      }

      const line = tokenNode.startPosition.row;
      if (seenLines.has(line)) {
        continue;
      }
      seenLines.add(line);

      // Extract other keyword args for config
      const callNode = getCapture(match.captures, "call");
      const configProperties = new Map<string, string>();
      let apiHost: string | null = null;

      if (callNode) {
        const argsNode = callNode.childForFieldName("arguments");
        if (argsNode) {
          for (const child of argsNode.namedChildren) {
            if (child.type === "pair") {
              const keyN = child.namedChildren[0];
              const valueN = child.namedChildren[1];
              if (
                keyN?.type === "hash_key_symbol" &&
                valueN &&
                keyN.text !== "api_key"
              ) {
                const key = keyN.text;
                let value = valueN.text;
                if (valueN.type === "string") {
                  const content = valueN.namedChildren.find(
                    (c) => c.type === "string_content",
                  );
                  if (content) {
                    value = content.text;
                  }
                }
                configProperties.set(key, value);
                if (key === "host" || key === "api_host") {
                  apiHost = value;
                }
              }
            }
          }
        }
      }

      results.push({
        token: cleanStringValue(tokenNode.text),
        tokenLine: tokenNode.startPosition.row,
        tokenStartCol: tokenNode.startPosition.column,
        tokenEndCol: tokenNode.endPosition.column,
        apiHost,
        configProperties,
      });
    }
  }

  return results;
}

function buildInitCall(
  tokenNode: Parser.SyntaxNode,
  configNode: Parser.SyntaxNode | undefined,
): PostHogInitCall {
  const token = cleanStringValue(tokenNode.text);
  const configProperties = new Map<string, string>();
  let apiHost: string | null = null;

  if (configNode) {
    for (const child of configNode.namedChildren) {
      if (child.type === "pair") {
        const keyN = child.childForFieldName("key");
        const valueN = child.childForFieldName("value");
        if (keyN && valueN) {
          const key = keyN.text.replace(/['"]/g, "");
          let value = valueN.text;
          if (valueN.type === "string") {
            const frag = valueN.namedChildren.find(
              (c) => c.type === "string_fragment",
            );
            if (frag) {
              value = frag.text;
            }
          }
          configProperties.set(key, value);
          if (key === "api_host" || key === "host") {
            apiHost = value;
          }
        }
      }
    }
  }

  return {
    token,
    tokenLine: tokenNode.startPosition.row,
    tokenStartCol: tokenNode.startPosition.column,
    tokenEndCol: tokenNode.endPosition.column,
    apiHost,
    configProperties,
  };
}

export async function findFunctions(
  pm: ParserManager,
  source: string,
  languageId: string,
): Promise<FunctionInfo[]> {
  const ready = await pm.ensureReady(languageId);
  if (!ready) {
    return [];
  }

  const { lang, family } = ready;
  const text = source;
  const tree = pm.parse(text, lang);
  if (!tree) {
    return [];
  }

  const query = pm.getQuery(lang, family.queries.functions);
  if (!query) {
    return [];
  }

  const functions: FunctionInfo[] = [];
  const matches = query.matches(tree.rootNode);

  for (const match of matches) {
    const nameNode = getCapture(match.captures, "func_name");
    const paramsNode = getCapture(match.captures, "func_params");
    const singleParamNode = getCapture(match.captures, "func_single_param");
    const bodyNode = getCapture(match.captures, "func_body");

    if (!nameNode || !bodyNode) {
      continue;
    }

    const name = nameNode.text;
    // Skip control flow keywords that might match method patterns
    if (["if", "for", "while", "switch", "catch", "else"].includes(name)) {
      continue;
    }

    const params = singleParamNode
      ? [singleParamNode.text]
      : paramsNode
        ? extractParams(paramsNode.text)
        : [];

    const bodyLine = bodyNode.startPosition.row;
    const bodyEndLine = bodyNode.endPosition.row;
    const nextLineIdx = bodyLine + 1;
    const lines = text.split("\n");
    const nextLine = nextLineIdx < lines.length ? lines[nextLineIdx] : "";
    const bodyIndent = nextLine.match(/^(\s*)/)?.[1] || "    ";

    functions.push({
      name,
      params,
      isComponent: /^[A-Z]/.test(name),
      bodyLine,
      bodyEndLine,
      bodyIndent,
    });
  }

  return functions;
}

export async function findFlagAssignments(
  pm: ParserManager,
  source: string,
  languageId: string,
): Promise<FlagAssignment[]> {
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

  const assignments: FlagAssignment[] = [];

  const assignQuery = pm.getQuery(lang, family.queries.flagAssignments);
  if (assignQuery) {
    const matches = assignQuery.matches(tree.rootNode);
    for (const match of matches) {
      const varNode = getCapture(match.captures, "var_name");
      const clientNode = getCapture(match.captures, "client");
      const methodNode = getCapture(match.captures, "method");
      const keyNode = getCapture(match.captures, "flag_key");

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

      // Check if there's already a type annotation by looking at the parent
      // In TS: `const flag: boolean = ...` — the variable_declarator has a type_annotation child
      const declarator = varNode.parent;
      const hasTypeAnnotation = declarator
        ? declarator.namedChildren.some((c) => c.type === "type_annotation")
        : false;

      assignments.push({
        varName: varNode.text,
        method,
        flagKey: cleanStringValue(keyNode.text),
        line: varNode.startPosition.row,
        varNameEndCol: varNode.endPosition.column,
        hasTypeAnnotation,
      });
    }
  }

  return assignments;
}
