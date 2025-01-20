// This file is compiled to schema.json, which becomes schema.py - allowing the frontend and backend to share types!

// Frontend note: DO NOT IMPORT ENUMS FROM THIS FILE, import them from the relevant /schema-*.ts file instead.
// For some reason Webpack (Storybook) and Sucrase (Jest) don't correctly process enums exported via `export * from ...`
// (even though our actual app's esbuild setup compiles perfectly well.)

/* eslint-disable simple-import-sort/exports */
export * from './schema-general'
export * from './schema-assistant-queries'
export * from './schema-assistant-messages'
/* eslint-enable simple-import-sort/exports */
