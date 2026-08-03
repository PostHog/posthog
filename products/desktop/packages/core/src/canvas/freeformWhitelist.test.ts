import { describe, expect, it } from "vitest";
import {
  buildImportMap,
  checkFreeformImports,
  FREEFORM_WHITELIST,
} from "./freeformWhitelist";

describe("checkFreeformImports", () => {
  it("accepts whitelisted imports", () => {
    const code = `
      import React from "react";
      import { createRoot } from "react-dom/client";
      import { LineChart } from "recharts";
      import dayjs from "dayjs";
      export default function App() { return null; }
    `;
    expect(checkFreeformImports(code)).toEqual({ ok: true, violations: [] });
  });

  it.each([
    ['import x from "lodash";', 'non-whitelisted module "lodash"'],
    ['import "node:fs";', 'non-whitelisted module "node:fs"'],
    ['import a from "./local";', 'non-whitelisted module "./local"'],
    ['export * from "axios";', 'non-whitelisted module "axios"'],
  ])("rejects non-whitelisted specifier: %s", (code, expected) => {
    const result = checkFreeformImports(code);
    expect(result.ok).toBe(false);
    expect(result.violations.some((v) => v.includes(expected))).toBe(true);
  });

  it.each([
    ['const m = import("react");', "dynamic import()"],
    ['const r = require("react");', "require()"],
    ["importScripts('evil.js');", "importScripts()"],
    ['const s = `<script src="x">`;', "inline <script>"],
  ])("rejects out-of-band loading: %s", (code, expected) => {
    const result = checkFreeformImports(code);
    expect(result.ok).toBe(false);
    expect(result.violations.some((v) => v.includes(expected))).toBe(true);
  });

  it("does not flag ordinary string literals as imports", () => {
    // Regression: the specifier regex must key off `from`/`import`, not any
    // quoted string after an import/export keyword.
    const code = `
      import React from "react";
      export default function App() {
        const label = "Add to cart";
        const url = "https://example.com/x";
        return React.createElement("button", null, label);
      }
    `;
    expect(checkFreeformImports(code)).toEqual({ ok: true, violations: [] });
  });

  it("collects multiple violations at once", () => {
    const code = `import x from "lodash"; const y = import("react");`;
    const result = checkFreeformImports(code);
    expect(result.ok).toBe(false);
    expect(result.violations.length).toBeGreaterThanOrEqual(2);
  });
});

describe("buildImportMap", () => {
  it("maps every whitelisted name to its esm url", () => {
    const map = buildImportMap();
    for (const entry of FREEFORM_WHITELIST) {
      expect(map.imports[entry.name]).toBe(entry.esm);
    }
  });
});
