export const PAGE_WORLD_ID = 1717;

const PRELUDE = `
const state = (window.__phBrowser ??= { next: 1, byRef: new Map(), byElement: new WeakMap() });
const refFor = (element) => {
  let ref = state.byElement.get(element);
  if (!ref) {
    ref = "e" + state.next++;
    state.byElement.set(element, ref);
    state.byRef.set(ref, new WeakRef(element));
  }
  return ref;
};
const elementFor = (ref) => {
  const element = state.byRef.get(ref)?.deref();
  return element && element.isConnected ? element : null;
};
const visible = (element) => {
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  const style = getComputedStyle(element);
  return style.visibility !== "hidden" && style.display !== "none";
};
const clean = (text, max) => {
  const value = (text || "").replace(/\\s+/g, " ").trim();
  return value.length > max ? value.slice(0, max - 1) + "…" : value;
};
`;

function script(body: string, args: unknown): string {
  return `(() => { ${PRELUDE} const args = ${JSON.stringify(args)}; ${body} })()`;
}

export function snapshotScript(maxChars: number): string {
  return script(
    `
const INTERACTIVE = "a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],[role=textbox],[contenteditable=true],[tabindex]:not([tabindex='-1'])";
const TEXT = "h1,h2,h3,h4,h5,h6,p,li,td,th,label,dt,dd,figcaption,blockquote";
const lines = [];
let size = 0;
const push = (line) => {
  if (size > args.maxChars) return false;
  lines.push(line);
  size += line.length + 1;
  return true;
};
push("url: " + location.href);
push("title: " + clean(document.title, 200));
const seen = new Set();
for (const element of document.querySelectorAll(INTERACTIVE + "," + TEXT)) {
  if (seen.has(element) || !visible(element)) continue;
  seen.add(element);
  const tag = element.tagName.toLowerCase();
  const role = element.getAttribute("role") || tag;
  if (element.matches(INTERACTIVE)) {
    const parts = ["[" + refFor(element) + "]", role];
    const label = element.getAttribute("aria-label") || element.getAttribute("title") || element.getAttribute("alt");
    const text = clean(label || element.innerText || element.value || "", 120);
    if (text && !(element instanceof HTMLInputElement && element.type === "password")) parts.push(JSON.stringify(text));
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
      if (element.type) parts.push("type=" + element.type);
      if (element.name) parts.push("name=" + element.name);
      if (element.placeholder) parts.push("placeholder=" + JSON.stringify(clean(element.placeholder, 60)));
      if (element.type === "password") parts.push(element.value ? "value=<hidden>" : "empty");
      else if (element.value && element.type !== "hidden") parts.push("value=" + JSON.stringify(clean(element.value, 80)));
      if (element.disabled) parts.push("disabled");
    }
    if (element instanceof HTMLInputElement && (element.type === "checkbox" || element.type === "radio")) parts.push(element.checked ? "checked" : "unchecked");
    if (element instanceof HTMLAnchorElement && element.href) parts.push("href=" + clean(element.href, 120));
    if (!push(parts.join(" "))) break;
  } else {
    if (element.closest(INTERACTIVE)) continue;
    const text = clean(element.innerText, 200);
    if (!text) continue;
    if (!push(tag + ": " + text)) break;
  }
}
if (size > args.maxChars) lines.push("… snapshot truncated");
return lines.join("\\n");
`,
    { maxChars },
  );
}

export function rectScript(ref: string): string {
  return script(
    `
const element = elementFor(args.ref);
if (!element) return null;
element.scrollIntoView({ block: "center", inline: "center" });
const rect = element.getBoundingClientRect();
return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, width: rect.width, height: rect.height, left: rect.left, top: rect.top };
`,
    { ref },
  );
}

export function focusScript(ref: string, clear: boolean): string {
  return script(
    `
const element = elementFor(args.ref);
if (!element) return false;
element.scrollIntoView({ block: "center" });
element.focus();
if (args.clear && ("value" in element)) {
  element.select?.();
} else if ("setSelectionRange" in element && typeof element.value === "string") {
  try { element.setSelectionRange(element.value.length, element.value.length); } catch {}
}
return document.activeElement === element;
`,
    { ref, clear },
  );
}

export function findTextScript(text: string): string {
  return script(
    `
const needle = args.text.toLowerCase();
const fieldText = (element) => [
  element.getAttribute("aria-label"),
  element.getAttribute("placeholder"),
  element.getAttribute("title"),
  element.getAttribute("alt"),
  ...[...(element.labels || [])].map((label) => label.innerText),
].filter(Boolean).join(" ");
for (const field of document.querySelectorAll("input:not([type=hidden]),textarea,select,img,[aria-label],[title]")) {
  if (visible(field) && clean(fieldText(field), 400).toLowerCase().includes(needle)) return refFor(field);
}
const candidates = document.querySelectorAll("a,button,[role=button],[role=link],label,summary,input[type=submit],input[type=button],h1,h2,h3,h4,h5,h6,p,li,span,div,td");
let best = null;
for (const element of candidates) {
  if (!visible(element)) continue;
  const own = clean(element.innerText || element.value || element.getAttribute("aria-label") || "", 400).toLowerCase();
  if (!own.includes(needle)) continue;
  if (!best || best.contains(element)) best = element;
}
return best ? refFor(best) : null;
`,
    { text },
  );
}

export function sensitivityScript(ref: string): string {
  return script(
    `
const element = elementFor(args.ref);
if (!element) return null;
const form = element.closest("form");
const fields = form ? [...form.querySelectorAll("input,select,textarea")] : [element];
const isPayment = (field) => /cc-|card|cvc|cvv|iban|expiry|exp-/i.test((field.getAttribute("autocomplete") || "") + " " + (field.name || "") + " " + (field.id || ""));
const password = fields.some((field) => field.type === "password");
const payment = fields.some(isPayment);
const submits = element.matches("button[type=submit],input[type=submit],button:not([type])") && !!form;
const filled = fields.some((field) => field.type !== "hidden" && field.type !== "submit" && typeof field.value === "string" && field.value.length > 0);
const label = clean(element.innerText || element.value || element.getAttribute("aria-label") || "", 80);
return {
  typesPassword: element instanceof HTMLInputElement && element.type === "password",
  password,
  payment,
  submitsData: submits && filled,
  destructive: /delete|remove|destroy|purchase|buy|pay|confirm|transfer|revoke/i.test(label),
  label,
};
`,
    { ref },
  );
}

export function evaluateScript(source: string): string {
  return `(async () => { const fn = (${source}); const value = await (typeof fn === "function" ? fn() : fn); return JSON.parse(JSON.stringify(value ?? null)); })()`;
}
