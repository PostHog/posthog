# HogQL Parser

Blazing fast HogQL parsing available in both Python and WebAssembly.

## Overview

This package provides a high-performance HogQL parser implemented in C++ with bindings for:

- **Python** - For use within the PostHog Django app
- **WebAssembly** - For use in JavaScript/TypeScript applications

The parser is split into three layers:

1. **`parser_core.cpp`** - Pure C++ parser with no dependencies on Python or JavaScript
2. **`parser_python.cpp`** - Python bindings for use in PostHog
3. **`parser_wasm.cpp`** - Emscripten bindings for JavaScript/TypeScript

## Python Usage

This package works in the context of the PostHog Django app, as it imports from `posthog.hogql`.

You can test changes locally by running:

```bash
pip install ./hogql_parser
```

---

## WebAssembly Usage

High-performance HogQL parser compiled to WebAssembly for use in JavaScript/TypeScript applications.

### Installation

```bash
npm install @posthog/hogql-parser
```

### Node.js Example

```javascript
import createHogQLParser from '@posthog/hogql-parser';

async function main() {
  const parser = await createHogQLParser();

  // Parse a HogQL expression
  const result = parser.parseExpr('user_id + 100');
  const ast = JSON.parse(result);

  if (ast.error) {
    console.error('Parse error:', ast.message);
  } else {
    console.log('Parsed AST:', ast);
  }
}

main();
```

### TypeScript Example

```typescript
import createHogQLParser from '@posthog/hogql-parser';

async function main() {
  const parser = await createHogQLParser();

  // Parse a SELECT statement
  const result = parser.parseSelect('SELECT * FROM events WHERE timestamp > now()');
  const ast = JSON.parse(result);

  console.log(ast);
}

main();
```

### Browser (ES6 Modules)

```html
<script type="module">
  import createHogQLParser from './dist/hogql_parser.js';

  const parser = await createHogQLParser();
  const result = parser.parseExpr('1 + 2');
  console.log(JSON.parse(result));
</script>
```

## API Reference

All functions return JSON strings that should be parsed with `JSON.parse()`.

### `parseExpr(input: string, isInternal?: boolean): string`

Parse a HogQL expression.

```javascript
const ast = JSON.parse(parser.parseExpr('toString(user_id)'));
```

### `parseSelect(input: string, isInternal?: boolean): string`

Parse a complete SELECT statement.

```javascript
const ast = JSON.parse(parser.parseSelect('SELECT * FROM events'));
```

### `parseOrderExpr(input: string, isInternal?: boolean): string`

Parse an ORDER BY expression.

```javascript
const ast = JSON.parse(parser.parseOrderExpr('timestamp DESC, user_id ASC'));
```

### `parseProgram(input: string, isInternal?: boolean): string`

Parse a complete Hog program.

```javascript
const ast = JSON.parse(parser.parseProgram('let x := 42; return x;'));
```

### `parseFullTemplateString(input: string, isInternal?: boolean): string`

Parse a Hog template string (F'...' syntax).

```javascript
const ast = JSON.parse(parser.parseFullTemplateString("f'Hello {name}'"));
```

### `parseStringLiteralText(input: string): string`

Unquote a string literal.

```javascript
const text = parser.parseStringLiteralText("'hello world'");
// Returns: "hello world"
```

### Parameters

- `input`: The HogQL string to parse
- `isInternal` (optional): If `true`, omits position information from the AST for smaller output (default: `false`)

## Error Handling

When parsing fails, the returned JSON contains an error object:

```javascript
const result = parser.parseExpr('INVALID SYNTAX');
const ast = JSON.parse(result);

if (ast.error) {
  console.error('Error type:', ast.type);      // 'SyntaxError' | 'ParsingError' | 'NotImplementedError'
  console.error('Message:', ast.message);      // Human-readable error message
  console.error('Start:', ast.start.offset);   // Error start position
  console.error('End:', ast.end.offset);       // Error end position
}
```

## Building from Source

### Prerequisites

1. **Emscripten SDK**: Install from https://emscripten.org/docs/getting_started/downloads.html

   ```bash
   git clone https://github.com/emscripten-core/emsdk.git
   cd emsdk
   ./emsdk install latest
   ./emsdk activate latest
   source ./emsdk_env.sh
   ```

2. **CMake**:

   ```bash
   brew install cmake
   ```

### Build Steps

```bash
# Clone the repository
git clone https://github.com/PostHog/posthog.git
cd posthog/common/hogql_parser

# Build ANTLR4 for WebAssembly (first time only)
./build_antlr4_wasm.sh

# Build the WASM module
./build_wasm.sh

# Test the build
node test.js
```

The build output will be in the `dist/` directory:

- `dist/hogql_parser.js` - JavaScript wrapper
- `dist/hogql_parser.wasm` - WebAssembly binary
- `dist/index.d.ts` - TypeScript definitions

## Performance

The WebAssembly parser is significantly faster than JavaScript-based parsers:

- ~10-100x faster than pure JavaScript parsers for complex queries
- Near-native C++ performance in the browser
- Small bundle size (~1MB total, ~200KB gzipped including WASM)

## License

MIT License - see LICENSE file for details

## Contributing

Issues and pull requests are welcome at https://github.com/PostHog/posthog/issues
