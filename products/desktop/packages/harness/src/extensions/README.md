# Harness extensions

Every harness capability is a **pi.dev extension**: a proper, first-class extension pi loads
through its own extension machinery. Each one lives in its own folder here and follows the same
shape, so adding the Nth extension is mechanical.

## Convention

```
src/extensions/<extension-name>/
  extension.ts     # REQUIRED — the real implementation
  index.ts         # REQUIRED — `export { default } from "./extension";`
  ...              # any supporting modules the extension needs
```

`index.ts` is loaded (as `dist/extensions/<name>/index.js`) by `-e`, instead of
`extension.js` directly, purely for display: pi's startup banner derives an
extension's name from its file path, and drops a trailing `index.ts`/`index.js`
segment in favor of the parent directory name. Loading `extension.js` directly
would show up as `<name>/extension.js` (and collide with any other extension
also named `extension.js`, backing off to even longer paths); loading
`index.js` shows the clean `<name>`.

`extension.ts` must:

1. `export default` a pi `ExtensionFactory` — `(pi: ExtensionAPI) => void | Promise<void>`.
   This is what `pi -e <path>` loads. It is zero-config; read any options from the environment.
2. `export` a named `create<Name>Extension(options)` that returns an `ExtensionFactory`.
   This is the configurable form used programmatically (CLI + SDK).

```ts
// src/extensions/<name>/extension.ts
import type { ExtensionAPI, ExtensionFactory } from "@earendil-works/pi-coding-agent";

export function createExampleExtension(options: ExampleOptions = {}): ExtensionFactory {
  return async (pi: ExtensionAPI) => {
    // pi.registerProvider(...) / pi.registerTool(...) / pi.on(...)
  };
}

export default function example(pi: ExtensionAPI): void | Promise<void> {
  return createExampleExtension()(pi);
}
```

## Registering it

Add one line to [`registry.ts`](./registry.ts):

```ts
const EXTENSIONS: HarnessExtension[] = [
  { name: "posthog-provider", create: createPosthogProviderExtension },
  { name: "example", create: createExampleExtension },
];
```

`registry.ts` is the single source of truth. Both harness entry paths consume it, so a registered
extension is loaded everywhere with no further wiring:

- **Pi CLI** (`src/cli.ts`) loads each compiled extension by file path through Pi's native `-e`
  argument.
- **Harness runtime** (`src/runtime.ts`) supplies named inline factories to Pi's
  `createAgentSessionServices()`.

The CLI path shows each extension's directory name in Pi's startup banner. The runtime path uses
named `InlineExtension` values, so those extensions appear as `<inline:name>` rather than anonymous
`<inline:N>` entries. Both paths use Pi's native extension loader.
