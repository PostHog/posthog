// ── Language-specific method sets and tree-sitter queries ──

export interface QueryStrings {
  postHogCalls: string;
  nodeCaptureCalls: string;
  pythonCaptureCalls?: string;
  goStructCalls?: string;
  rubyCaptureCalls?: string;
  identifierArgCalls: string;
  dynamicCalls: string;
  flagAssignments: string;
  functions: string;
  clientAliases: string;
  constructorAliases: string;
  destructuredMethods: string;
  bareFunctionCalls: string;
  /** Import statements — only populated for languages where cross-file wrapper resolution is supported. */
  imports?: string;
}

export interface LangFamily {
  wasm: string;
  captureMethods: Set<string>;
  flagMethods: Set<string>;
  allMethods: Set<string>;
  queries: QueryStrings;
}

// ── Method sets per language ──

const JS_CAPTURE_METHODS = new Set(["capture"]);
const JS_FLAG_METHODS = new Set([
  "getFeatureFlag",
  "isFeatureEnabled",
  "getFeatureFlagPayload",
  "getFeatureFlagResult",
  "isFeatureFlagEnabled",
  "getRemoteConfig",
]);
const JS_ALL_METHODS = new Set([...JS_CAPTURE_METHODS, ...JS_FLAG_METHODS]);

const PY_CAPTURE_METHODS = new Set(["capture"]);
const PY_FLAG_METHODS = new Set([
  "feature_enabled",
  "is_feature_enabled",
  "get_feature_flag",
  "get_feature_flag_payload",
  "get_remote_config",
]);
const PY_ALL_METHODS = new Set([...PY_CAPTURE_METHODS, ...PY_FLAG_METHODS]);

const GO_CAPTURE_METHODS = new Set(["Enqueue"]);
const GO_FLAG_METHODS = new Set([
  "GetFeatureFlag",
  "IsFeatureEnabled",
  "GetFeatureFlagPayload",
]);
const GO_ALL_METHODS = new Set([...GO_CAPTURE_METHODS, ...GO_FLAG_METHODS]);

const RB_CAPTURE_METHODS = new Set(["capture"]);
const RB_FLAG_METHODS = new Set([
  "is_feature_enabled",
  "get_feature_flag",
  "get_feature_flag_payload",
  "get_remote_config_payload",
]);
const RB_ALL_METHODS = new Set([...RB_CAPTURE_METHODS, ...RB_FLAG_METHODS]);

// ── Default client names ──

export const CLIENT_NAMES = new Set(["posthog", "client", "ph"]);

// ── All flag methods across languages (for stale flag scanning) ──

export const ALL_FLAG_METHODS = new Set([
  ...JS_FLAG_METHODS,
  ...PY_FLAG_METHODS,
  ...GO_FLAG_METHODS,
  ...RB_FLAG_METHODS,
]);

// ── Tree-sitter queries ──

const JS_QUERIES: QueryStrings = {
  postHogCalls: `
    (call_expression
      function: (member_expression
        object: (_) @client
        property: (property_identifier) @method)
      arguments: (arguments . (string (string_fragment) @key))) @call

    (call_expression
      function: (member_expression
        object: (_) @client
        property: (property_identifier) @method)
      arguments: (arguments . (template_string (string_fragment) @key))) @call
  `,

  nodeCaptureCalls: `
    (call_expression
      function: (member_expression
        object: (_) @client
        property: (property_identifier) @method)
      arguments: (arguments .
        (object
          (pair
            key: (property_identifier) @prop_name
            value: (string (string_fragment) @key))))) @call
  `,

  flagAssignments: `
    (lexical_declaration
      (variable_declarator
        name: (identifier) @var_name
        value: (call_expression
          function: (member_expression
            object: (_) @client
            property: (property_identifier) @method)
          arguments: (arguments . (string (string_fragment) @flag_key))))) @assignment

    (variable_declaration
      (variable_declarator
        name: (identifier) @var_name
        value: (call_expression
          function: (member_expression
            object: (_) @client
            property: (property_identifier) @method)
          arguments: (arguments . (string (string_fragment) @flag_key))))) @assignment

    (lexical_declaration
      (variable_declarator
        name: (identifier) @var_name
        value: (await_expression
          (call_expression
            function: (member_expression
              object: (_) @client
              property: (property_identifier) @method)
            arguments: (arguments . (string (string_fragment) @flag_key)))))) @assignment

    (variable_declaration
      (variable_declarator
        name: (identifier) @var_name
        value: (await_expression
          (call_expression
            function: (member_expression
              object: (_) @client
              property: (property_identifier) @method)
            arguments: (arguments . (string (string_fragment) @flag_key)))))) @assignment
  `,

  functions: `
    (function_declaration
      name: (identifier) @func_name
      parameters: (formal_parameters) @func_params
      body: (statement_block) @func_body)

    (export_statement
      declaration: (function_declaration
        name: (identifier) @func_name
        parameters: (formal_parameters) @func_params
        body: (statement_block) @func_body))

    (lexical_declaration
      (variable_declarator
        name: (identifier) @func_name
        value: (arrow_function
          parameters: (formal_parameters) @func_params
          body: (statement_block) @func_body)))

    (lexical_declaration
      (variable_declarator
        name: (identifier) @func_name
        value: (arrow_function
          parameter: (identifier) @func_single_param
          body: (statement_block) @func_body)))

    (method_definition
      name: (property_identifier) @func_name
      parameters: (formal_parameters) @func_params
      body: (statement_block) @func_body)
  `,

  clientAliases: `
    (lexical_declaration
      (variable_declarator
        name: (identifier) @alias
        value: (identifier) @source))

    (variable_declaration
      (variable_declarator
        name: (identifier) @alias
        value: (identifier) @source))
  `,

  constructorAliases: `
    (lexical_declaration
      (variable_declarator
        name: (identifier) @alias
        value: (new_expression
          constructor: (identifier) @class_name)))

    (variable_declaration
      (variable_declarator
        name: (identifier) @alias
        value: (new_expression
          constructor: (identifier) @class_name)))
  `,

  destructuredMethods: `
    (lexical_declaration
      (variable_declarator
        name: (object_pattern
          (shorthand_property_identifier_pattern) @method_name)
        value: (identifier) @source))
  `,

  bareFunctionCalls: `
    (call_expression
      function: (identifier) @func_name
      arguments: (arguments . (string (string_fragment) @key))) @call
  `,

  identifierArgCalls: `
    (call_expression
      function: (member_expression
        object: (_) @client
        property: (property_identifier) @method)
      arguments: (arguments . (identifier) @arg_id)) @call
  `,

  dynamicCalls: `
    (call_expression
      function: (member_expression
        object: (_) @client
        property: (property_identifier) @method)
      arguments: (arguments . (_) @first_arg)) @call
  `,

  imports: `
    (import_statement
      (import_clause
        (identifier) @default_name)
      source: (string (string_fragment) @source)) @stmt

    (import_statement
      (import_clause
        (named_imports
          (import_specifier
            name: (identifier) @imported_name) @spec))
      source: (string (string_fragment) @source)) @stmt

    (import_statement
      (import_clause
        (named_imports
          (import_specifier
            name: (identifier) @imported_name
            alias: (identifier) @local_name) @spec))
      source: (string (string_fragment) @source)) @stmt

    (import_statement
      (import_clause
        (namespace_import
          (identifier) @namespace_name))
      source: (string (string_fragment) @source)) @stmt
  `,
};

const PY_QUERIES: QueryStrings = {
  postHogCalls: `
    (call
      function: (attribute
        object: (_) @client
        attribute: (identifier) @method)
      arguments: (argument_list . (string (string_content) @key))) @call
  `,

  nodeCaptureCalls: "",

  pythonCaptureCalls: `
    (call
      function: (attribute
        object: (_) @client
        attribute: (identifier) @method)
      arguments: (argument_list (string) . (string (string_content) @key))) @call

    (call
      function: (attribute
        object: (_) @client
        attribute: (identifier) @method)
      arguments: (argument_list
        (keyword_argument
          name: (identifier) @kwarg_name
          value: (string (string_content) @key)))) @call
  `,

  flagAssignments: `
    (expression_statement
      (assignment
        left: (identifier) @var_name
        right: (call
          function: (attribute
            object: (_) @client
            attribute: (identifier) @method)
          arguments: (argument_list . (string (string_content) @flag_key))))) @assignment
  `,

  functions: `
    (function_definition
      name: (identifier) @func_name
      parameters: (parameters) @func_params
      body: (block) @func_body)
  `,

  clientAliases: `
    (expression_statement
      (assignment
        left: (identifier) @alias
        right: (identifier) @source))
  `,

  constructorAliases: `
    (expression_statement
      (assignment
        left: (identifier) @alias
        right: (call
          function: (identifier) @class_name
          arguments: (argument_list))))
  `,

  destructuredMethods: "",

  bareFunctionCalls: `
    (call
      function: (identifier) @func_name
      arguments: (argument_list . (string (string_content) @key))) @call
  `,

  identifierArgCalls: `
    (call
      function: (attribute
        object: (_) @client
        attribute: (identifier) @method)
      arguments: (argument_list . (identifier) @arg_id)) @call
  `,

  dynamicCalls: `
    (call
      function: (attribute
        object: (_) @client
        attribute: (identifier) @method)
      arguments: (argument_list . (_) @first_arg)) @call
  `,

  imports: `
    (import_from_statement
      module_name: (dotted_name) @source
      name: (dotted_name) @imported_name) @stmt

    (import_from_statement
      module_name: (dotted_name) @source
      name: (aliased_import
        name: (dotted_name) @imported_name
        alias: (identifier) @local_name)) @stmt

    (import_from_statement
      module_name: (relative_import
        (import_prefix) @relative_prefix
        (dotted_name)? @relative_name)
      name: (dotted_name) @imported_name) @stmt

    (import_from_statement
      module_name: (relative_import
        (import_prefix) @relative_prefix
        (dotted_name)? @relative_name)
      name: (aliased_import
        name: (dotted_name) @imported_name
        alias: (identifier) @local_name)) @stmt
  `,
};

const GO_QUERIES: QueryStrings = {
  postHogCalls: `
    (call_expression
      function: (selector_expression
        operand: (_) @client
        field: (field_identifier) @method)
      arguments: (argument_list . (interpreted_string_literal) @key)) @call
  `,

  nodeCaptureCalls: "",

  goStructCalls: `
    (call_expression
      function: (selector_expression
        operand: (_) @client
        field: (field_identifier) @method)
      arguments: (argument_list
        (composite_literal
          body: (literal_value
            (keyed_element
              (literal_element (identifier) @field_name)
              (literal_element (interpreted_string_literal) @key)))))) @call
  `,

  flagAssignments: `
    (short_var_declaration
      left: (expression_list . (identifier) @var_name .)
      right: (expression_list
        (call_expression
          function: (selector_expression
            operand: (_) @client
            field: (field_identifier) @method)
          arguments: (argument_list . (interpreted_string_literal) @flag_key)))) @assignment

    (short_var_declaration
      left: (expression_list . (identifier) @var_name (_))
      right: (expression_list
        (call_expression
          function: (selector_expression
            operand: (_) @client
            field: (field_identifier) @method)
          arguments: (argument_list . (interpreted_string_literal) @flag_key)))) @assignment
  `,

  functions: `
    (function_declaration
      name: (identifier) @func_name
      parameters: (parameter_list) @func_params
      body: (block) @func_body)

    (method_declaration
      name: (field_identifier) @func_name
      parameters: (parameter_list) @func_params
      body: (block) @func_body)
  `,

  clientAliases: "",

  constructorAliases: `
    (short_var_declaration
      left: (expression_list (identifier) @alias)
      right: (expression_list
        (call_expression
          function: (selector_expression
            operand: (identifier) @pkg_name
            field: (field_identifier) @func_name))))

    (short_var_declaration
      left: (expression_list (identifier) @alias (_))
      right: (expression_list
        (call_expression
          function: (selector_expression
            operand: (identifier) @pkg_name
            field: (field_identifier) @func_name))))
  `,

  destructuredMethods: "",

  bareFunctionCalls: "",

  identifierArgCalls: `
    (call_expression
      function: (selector_expression
        operand: (_) @client
        field: (field_identifier) @method)
      arguments: (argument_list . (identifier) @arg_id)) @call
  `,

  dynamicCalls: `
    (call_expression
      function: (selector_expression
        operand: (_) @client
        field: (field_identifier) @method)
      arguments: (argument_list . (_) @first_arg)) @call
  `,
};

const RB_QUERIES: QueryStrings = {
  postHogCalls: `
    (call
      receiver: (_) @client
      method: (identifier) @method
      arguments: (argument_list . (string (string_content) @key))) @call
  `,

  nodeCaptureCalls: "",

  rubyCaptureCalls: `
    (call
      receiver: (_) @client
      method: (identifier) @method
      arguments: (argument_list
        (pair
          (hash_key_symbol) @kwarg_name
          (string (string_content) @key)))) @call
  `,

  flagAssignments: `
    (assignment
      left: (identifier) @var_name
      right: (call
        receiver: (_) @client
        method: (identifier) @method
        arguments: (argument_list . (string (string_content) @flag_key)))) @assignment
  `,

  functions: `
    (method
      name: (identifier) @func_name
      parameters: (method_parameters) @func_params
      body: (_) @func_body)
  `,

  clientAliases: `
    (assignment
      left: (identifier) @alias
      right: (identifier) @source)
  `,

  constructorAliases: `
    (assignment
      left: (identifier) @alias
      right: (call
        receiver: (scope_resolution
          scope: (constant) @scope_name
          name: (constant) @class_name)
        method: (identifier) @method_name))
  `,

  destructuredMethods: "",

  bareFunctionCalls: `
    (call
      method: (identifier) @func_name
      arguments: (argument_list . (string (string_content) @key))) @call
  `,

  identifierArgCalls: `
    (call
      receiver: (_) @client
      method: (identifier) @method
      arguments: (argument_list . (identifier) @arg_id)) @call

    (call
      receiver: (_) @client
      method: (identifier) @method
      arguments: (argument_list . (constant) @arg_id)) @call
  `,

  dynamicCalls: `
    (call
      receiver: (_) @client
      method: (identifier) @method
      arguments: (argument_list . (_) @first_arg)) @call
  `,
};

// ── File extension → language ID mapping ──

export const EXT_TO_LANG_ID: Record<string, string> = {
  ".js": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".jsx": "javascriptreact",
  ".ts": "typescript",
  ".mts": "typescript",
  ".cts": "typescript",
  ".tsx": "typescriptreact",
  ".py": "python",
  ".pyw": "python",
  ".go": "go",
  ".rb": "ruby",
  ".rake": "ruby",
  ".gemspec": "ruby",
};

// ── Language → family mapping ──

export const LANG_FAMILIES: Record<string, LangFamily> = {
  javascript: {
    wasm: "tree-sitter-javascript.wasm",
    captureMethods: JS_CAPTURE_METHODS,
    flagMethods: JS_FLAG_METHODS,
    allMethods: JS_ALL_METHODS,
    queries: JS_QUERIES,
  },
  javascriptreact: {
    wasm: "tree-sitter-javascript.wasm",
    captureMethods: JS_CAPTURE_METHODS,
    flagMethods: JS_FLAG_METHODS,
    allMethods: JS_ALL_METHODS,
    queries: JS_QUERIES,
  },
  typescript: {
    wasm: "tree-sitter-typescript.wasm",
    captureMethods: JS_CAPTURE_METHODS,
    flagMethods: JS_FLAG_METHODS,
    allMethods: JS_ALL_METHODS,
    queries: JS_QUERIES,
  },
  typescriptreact: {
    wasm: "tree-sitter-tsx.wasm",
    captureMethods: JS_CAPTURE_METHODS,
    flagMethods: JS_FLAG_METHODS,
    allMethods: JS_ALL_METHODS,
    queries: JS_QUERIES,
  },
  python: {
    wasm: "tree-sitter-python.wasm",
    captureMethods: PY_CAPTURE_METHODS,
    flagMethods: PY_FLAG_METHODS,
    allMethods: PY_ALL_METHODS,
    queries: PY_QUERIES,
  },
  go: {
    wasm: "tree-sitter-go.wasm",
    captureMethods: GO_CAPTURE_METHODS,
    flagMethods: GO_FLAG_METHODS,
    allMethods: GO_ALL_METHODS,
    queries: GO_QUERIES,
  },
  ruby: {
    wasm: "tree-sitter-ruby.wasm",
    captureMethods: RB_CAPTURE_METHODS,
    flagMethods: RB_FLAG_METHODS,
    allMethods: RB_ALL_METHODS,
    queries: RB_QUERIES,
  },
};
