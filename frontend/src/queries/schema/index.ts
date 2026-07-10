// This file is compiled to schema.json, which becomes schema.py - allowing the frontend and backend to share types!

// Frontend note: DO NOT IMPORT ENUMS FROM THIS FILE, import them from the relevant /schema-*.ts file instead.
// For some reason Webpack (Storybook) and Sucrase (Jest) don't correctly process enums exported via `export * from ...`
// (even though our actual app's esbuild setup compiles perfectly well.)

// ⚠️ Before adding a new schema-*.ts file here: this pipeline is for frontend-AUTHORED query types only.
// Backend-owned shapes (API responses, contracts the backend validates or emits) do NOT belong here -
// declare them in a serializer or Pydantic model and let the backend -> frontend OpenAPI/Orval pipeline
// generate the TS. See docs/published/handbook/engineering/type-system.md.
// sort-imports-ignore
export * from './schema-assistant-artifacts'
export * from './schema-assistant-error-tracking'
export * from './schema-assistant-queries'
export * from './schema-assistant-replay'
export * from './schema-assistant-revenue-analytics'
export * from './schema-assistant-web-analytics'
export * from './schema-general'
export * from './schema-surveys'
// Must be kept after schema-general.
export * from './schema-assistant-messages'
