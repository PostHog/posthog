# @posthog/enricher

Detect and enrich PostHog SDK usage in source code. Uses tree-sitter AST analysis to find `capture()` calls, feature flag checks, `init()` calls, and variant branches across JavaScript, TypeScript, Python, Go, and Ruby.

## Quick start

```typescript
import { PostHogEnricher } from "@posthog/enricher";

const enricher = new PostHogEnricher();

// Parse from source string
const result = await enricher.parse(sourceCode, "typescript");

// Or parse from file (auto-detects language from extension)
const result = await enricher.parseFile("/path/to/app.tsx");

result.events;     // [{ name: "purchase", line: 5, dynamic: false }]
result.flagChecks; // [{ method: "getFeatureFlag", flagKey: "new-checkout", line: 8 }]
result.flagKeys;   // ["new-checkout"]
result.eventNames; // ["purchase"]
result.toList();   // [{ type: "event", line: 5, name: "purchase", method: "capture" }, ...]
```

## Enriching from the PostHog API

Let the enricher fetch everything it needs based on what `parse()` found — feature flags, experiments, event definitions, and event volume/user stats:

```typescript
const result = await enricher.parse(sourceCode, "typescript");
const enriched = await result.enrichFromApi({
  apiKey: "phx_...",
  host: "https://us.posthog.com",
  projectId: 12345,
});

// Flags with staleness, rollout, experiment info
enriched.flags;
// [{ flagKey: "new-checkout", flagType: "boolean", staleness: "fully_rolled_out",
//    rollout: 100, experiment: { name: "Checkout v2", ... }, ... }]

// Events with definition, volume, unique users
enriched.events;
// [{ eventName: "purchase", verified: true, lastSeenAt: "2025-04-01",
//    tags: ["revenue"], stats: { volume: 12500, uniqueUsers: 3200 }, ... }]

// Flat list combining both
enriched.toList();
// [{ type: "event", name: "purchase", verified: true, volume: 12500, ... },
//  { type: "flag", name: "new-checkout", flagType: "boolean", staleness: "fully_rolled_out", ... }]

// Source code with inline annotation comments
enriched.toComments();
// // [PostHog] Event: "purchase" (verified) — 12,500 events — 3,200 users
// posthog.capture("purchase", { amount: 99 });
//
// // [PostHog] Flag: "new-checkout" — boolean — 100% rolled out — STALE (fully_rolled_out)
// const flag = posthog.getFeatureFlag("new-checkout");
```

## Supported languages

| Language | ID | Capture | Flags | Init | Variants |
|---|---|---|---|---|---|
| JavaScript | `javascript` | yes | yes | yes | yes |
| TypeScript | `typescript` | yes | yes | yes | yes |
| JSX | `javascriptreact` | yes | yes | yes | yes |
| TSX | `typescriptreact` | yes | yes | yes | yes |
| Python | `python` | yes | yes | yes | yes |
| Go | `go` | yes | yes | yes | yes |
| Ruby | `ruby` | yes | yes | yes | yes |

## API reference

### `PostHogEnricher`

Main entry point. Owns the tree-sitter parser lifecycle.

```typescript
const enricher = new PostHogEnricher();
const result = await enricher.parse(source, languageId);
const result = await enricher.parseFile("/path/to/file.ts");
enricher.dispose();
```

### `ParseResult`

Returned by `enricher.parse()`. Contains all detected PostHog SDK usage.

| Property / Method | Type | Description |
|---|---|---|
| `calls` | `PostHogCall[]` | All detected SDK method calls |
| `initCalls` | `PostHogInitCall[]` | `posthog.init()` and constructor calls |
| `flagAssignments` | `FlagAssignment[]` | Flag result variable assignments |
| `variantBranches` | `VariantBranch[]` | If/switch branches on flag values |
| `functions` | `FunctionInfo[]` | Function definitions in the file |
| `events` | `CapturedEvent[]` | Capture calls only |
| `flagChecks` | `FlagCheck[]` | Flag method calls only |
| `flagKeys` | `string[]` | Unique flag keys |
| `eventNames` | `string[]` | Unique event names |
| `toList()` | `ListItem[]` | Flat sorted list of all SDK usage |
| `enrichFromApi(config)` | `Promise<EnrichedResult>` | Fetch from PostHog API and enrich |

### `PostHogEnricher` methods

| Method | Description |
|---|---|
| `constructor()` | Create enricher. Bundled grammars are auto-located at runtime. |
| `parse(source, languageId)` | Parse a source code string with an explicit language ID |
| `parseFile(filePath)` | Read a file and parse it, auto-detecting language from the file extension |
| `isSupported(langId)` | Check if a language ID is supported |
| `supportedLanguages` | List of supported language IDs |
| `updateConfig(config)` | Customize detection behavior |
| `dispose()` | Clean up parser resources |

### `EnrichedResult`

Returned by `enrich()` or `enrichFromApi()`. Detection combined with PostHog context.

| Property / Method | Type | Description |
|---|---|---|
| `flags` | `EnrichedFlag[]` | Flags grouped by key with type, staleness, rollout, experiment |
| `events` | `EnrichedEvent[]` | Events grouped by name with definition, stats, tags |
| `toList()` | `EnrichedListItem[]` | Flat list with all metadata |
| `toComments()` | `string` | Source code with inline annotation comments |

### `EnricherApiConfig`

```typescript
interface EnricherApiConfig {
  apiKey: string;
  host: string;       // e.g. "https://us.posthog.com"
  projectId: number;
}
```

### `EnrichedFlag`

```typescript
interface EnrichedFlag {
  flagKey: string;
  flagType: "boolean" | "multivariate" | "remote_config";
  staleness: StalenessReason | null;
  rollout: number | null;
  variants: { key: string; rollout_percentage: number }[];
  flag: FeatureFlag | undefined;
  experiment: Experiment | undefined;
  occurrences: FlagCheck[];
}
```

### `EnrichedEvent`

```typescript
interface EnrichedEvent {
  eventName: string;
  verified: boolean;
  lastSeenAt: string | null;
  tags: string[];
  stats: { volume?: number; uniqueUsers?: number } | undefined;
  definition: EventDefinition | undefined;
  occurrences: CapturedEvent[];
}
```

## Detection API

The lower-level detection API is also exported for direct use (this is the same API used by the PostHog VSCode extension):

```typescript
import { PostHogDetector } from "@posthog/enricher";

const detector = new PostHogDetector();

const calls = await detector.findPostHogCalls(source, "typescript");
const initCalls = await detector.findInitCalls(source, "typescript");
const branches = await detector.findVariantBranches(source, "typescript");
const assignments = await detector.findFlagAssignments(source, "typescript");
const functions = await detector.findFunctions(source, "typescript");

detector.dispose();
```

### Flag classification utilities

```typescript
import { classifyFlagType, classifyStaleness } from "@posthog/enricher";

classifyFlagType(flag);                           // "boolean" | "multivariate" | "remote_config"
classifyStaleness(key, flag, experiments, opts);   // StalenessReason | null
```

## Logging

Warnings are silenced by default. To receive them:

```typescript
import { setLogger } from "@posthog/enricher";

setLogger({ warn: console.warn });
```

## Setup

Grammar files are bundled with the package and auto-located at runtime — no manual setup needed.

For development, run `pnpm fetch-grammars` to rebuild the WASM grammar files in the `grammars/` directory.
