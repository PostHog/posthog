// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  focusedFormScript,
  rectScript,
  sensitivityScript,
  snapshotScript,
} from "./page-scripts";

type Box = { x: number; y: number } | null;

function run<T>(code: string): T {
  return new Function(`return ${code}`)() as T;
}

function refFor(snapshot: string, needle: string): string {
  const line = snapshot.split("\n").find((entry) => entry.includes(needle));
  const ref = line?.match(/^\[([^\]]+)\]/)?.[1];
  if (!ref) throw new Error(`No ref for ${needle} in:\n${snapshot}`);
  return ref;
}

describe("page scripts", () => {
  let pointTarget: Element | null = null;

  beforeEach(() => {
    Reflect.deleteProperty(window, "__phBrowser");
    Object.defineProperty(HTMLElement.prototype, "innerText", {
      configurable: true,
      get() {
        return (this as HTMLElement).textContent ?? "";
      },
    });
    HTMLElement.prototype.getBoundingClientRect = function () {
      const hidden = (this as HTMLElement).closest("[data-hidden]");
      const size = hidden ? 0 : 20;
      return new DOMRect(10, 10, size, size);
    };
    HTMLElement.prototype.scrollIntoView = () => undefined;
    pointTarget = null;
    document.elementFromPoint = () => pointTarget;
  });

  afterEach(() => {
    document.body.removeAttribute("data-hidden");
    document.body.innerHTML = "";
  });

  it("keeps secret field values out of the snapshot", () => {
    document.body.innerHTML = `
      <input type="text" autocomplete="current-password" name="shown" value="hunter2" />
      <textarea name="card-number">4242 4242 4242 4242</textarea>
      <input type="email" name="email" value="me@example.com" />
      <label><input type="checkbox" /> I agree</label>
      <div role="switch" aria-checked="true" tabindex="0">Dark mode</div>
    `;

    const snapshot = run<string>(snapshotScript(4_000));

    expect(snapshot).not.toContain("hunter2");
    expect(snapshot).not.toContain("4242");
    expect(snapshot).toContain('value="me@example.com"');
    expect(snapshot).toMatch(/input "I agree" type=checkbox/);
    expect(snapshot).toContain("checked=true");
  });

  it("keeps the snapshot inside its budget, marker included", () => {
    document.body.innerHTML = Array.from(
      { length: 40 },
      (_, index) => `<p>Paragraph number ${index} with some text</p>`,
    ).join("");

    const snapshot = run<string>(snapshotScript(300));

    expect(snapshot.length).toBeLessThanOrEqual(300);
    expect(snapshot.endsWith("… snapshot truncated")).toBe(true);
  });

  it.each([
    {
      name: "a submitter outside its form",
      html: `<form id="login"><input type="password" value="x" /></form><button form="login" type="submit">Go</button>`,
      pick: "Go",
      expected: { password: true, submitsData: true },
    },
    {
      name: "an image submitter",
      html: `<form><input name="city" value="Paris" /><input type="image" alt="Send" /></form>`,
      pick: "Send",
      expected: { submitsData: true },
    },
    {
      name: "an icon button named by aria-label",
      html: `<button aria-label="Delete project">×</button>`,
      pick: "Delete project",
      expected: { destructive: true, label: "Delete project" },
    },
  ])("classifies $name", ({ html, pick, expected }) => {
    document.body.innerHTML = html;
    const ref = refFor(run<string>(snapshotScript(4_000)), pick);

    expect(run(sensitivityScript(ref))).toMatchObject(expected);
  });

  it("never puts a typed secret in the sensitivity label", () => {
    document.body.innerHTML = `<input type="password" placeholder="Password" value="hunter2" />`;
    const ref = refFor(run<string>(snapshotScript(4_000)), "type=password");

    const result = run<{ label: string; typesPassword: boolean }>(
      sensitivityScript(ref),
    );

    expect(result.typesPassword).toBe(true);
    expect(result.label).not.toContain("hunter2");
  });

  it("treats a focused password field outside a form as sensitive", () => {
    document.body.innerHTML = `<input type="password" value="x" />`;
    (document.querySelector("input") as HTMLInputElement).focus();

    expect(run(focusedFormScript())).toMatchObject({
      password: true,
      filled: true,
    });
  });

  it("rejects a reference from an earlier page", () => {
    document.body.innerHTML = `<button>Save</button>`;
    const ref = refFor(run<string>(snapshotScript(4_000)), "Save");
    Reflect.deleteProperty(window, "__phBrowser");

    expect(run<Box>(rectScript(ref))).toBeNull();
  });

  it.each([
    { problem: "hidden", html: `<button>Save</button>`, hide: true },
    {
      problem: "covered",
      html: `<button>Save</button><div id="modal">Modal</div>`,
      hide: false,
    },
  ])(
    "refuses to click an element that is $problem",
    ({ problem, html, hide }) => {
      document.body.innerHTML = html;
      const ref = refFor(run<string>(snapshotScript(4_000)), "Save");
      if (hide) document.body.setAttribute("data-hidden", "");
      pointTarget = document.getElementById("modal");

      expect(run(rectScript(ref, true))).toEqual({ problem });
    },
  );
});
