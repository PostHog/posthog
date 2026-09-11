# Node.js linting

Run `pnpm --filter=@posthog/nodejs lint` to check Node.js services and `pnpm --filter=@posthog/nodejs lint:fix` to apply safe fixes.
`hogli format:nodejs <files>` and the proto-generation commands use the same lint entrypoint.
Prettier remains the formatter: run `pnpm --filter=@posthog/nodejs format:check` to check formatting.

The Node.js configuration lives in `nodejs/.oxlintrc.json` and is independent of the frontend and image-scrub sidecar configurations.
The parent command excludes the standalone sidecar, generated IDL, build output, dependencies, `bin`, and `dev` directories.
It checks JavaScript and TypeScript files with the same extension scope as the former ESLint command.

Oxlint runs the explicitly configured syntax rules and four type-aware rules through `oxlint-tsgolint`: `require-await`, `await-thenable`, `no-floating-promises`, and `no-misused-promises`.
The last rule permits promise-returning callbacks where a void return is expected.
The floating-promise exception applies to `**/tests/**/*.ts` and `src/celery/**/*.ts`, but not to colocated tests elsewhere.
Ingestion files also reject parent-relative imports.

The JavaScript plugin preserves the `JSON.parse` restriction and directive-pair checks; the focused-test plugin retains its existing test-function coverage.
Use named `eslint-disable` or `oxlint-disable` directives for necessary exceptions.
Unused directives fail linting.
The entrypoint separately rejects blanket disables because Oxlint can suppress a JavaScript plugin's own directive errors.
This guard parses one file at a time without creating a TypeScript type-checking program.

Type checking remains a separate command: `pnpm --filter=@posthog/nodejs typescript:check`.
Build workspace prerequisites with `bin/turbo --filter=@posthog/nodejs prepare` first.
