export function pageKit() {
  window.__phBrowser ??= {
    page: Math.random().toString(36).slice(2, 6),
    next: 1,
    byRef: new Map(),
    byElement: new WeakMap(),
  };
  const state = window.__phBrowser;

  const refFor = (element) => {
    let ref = state.byElement.get(element);
    if (!ref) {
      ref = `${state.page}-${state.next++}`;
      state.byElement.set(element, ref);
      state.byRef.set(ref, new WeakRef(element));
    }
    return ref;
  };

  const elementFor = (ref) => {
    const element = state.byRef.get(ref)?.deref();
    return element?.isConnected ? element : null;
  };

  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    const style = getComputedStyle(element);
    return style.visibility !== "hidden" && style.display !== "none";
  };

  const clean = (text, max) => {
    const value = (text || "").replace(/\s+/g, " ").trim();
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  };

  const isField = (element) =>
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement;

  const formOf = (element) => element.form ?? element.closest?.("form") ?? null;

  const formFields = (form) => [...form.elements].filter(isField);

  const autocompleteOf = (field) =>
    (field.getAttribute("autocomplete") || "").toLowerCase();

  const isPasswordField = (field) =>
    isField(field) &&
    (field.type === "password" ||
      /current-password|new-password|one-time-code/.test(
        autocompleteOf(field),
      ));

  const isPayment = (field) =>
    isField(field) &&
    /cc-|card|cvc|cvv|iban|expiry|exp-/i.test(
      `${autocompleteOf(field)} ${field.name || ""} ${field.id || ""}`,
    );

  const isSecret = (field) => isPasswordField(field) || isPayment(field);

  const NON_VALUE_TYPES = ["hidden", "submit", "button", "reset", "image"];

  const isFilled = (field) => {
    if (field.type === "checkbox" || field.type === "radio")
      return field.checked;
    if (NON_VALUE_TYPES.includes(field.type)) return false;
    return typeof field.value === "string" && field.value.length > 0;
  };

  const isSubmitter = (element) =>
    (element instanceof HTMLButtonElement && element.type === "submit") ||
    (element instanceof HTMLInputElement &&
      (element.type === "submit" || element.type === "image"));

  const isButtonLike = (element) =>
    element instanceof HTMLButtonElement ||
    (element instanceof HTMLInputElement &&
      ["submit", "button", "reset", "image"].includes(element.type));

  const labelText = (element) =>
    [...(element.labels || [])].map((label) => label.innerText).join(" ");

  const nameOf = (element) =>
    element.getAttribute("aria-label") ||
    labelText(element) ||
    element.getAttribute("title") ||
    element.getAttribute("alt") ||
    element.innerText ||
    (isButtonLike(element) ? element.value : "") ||
    "";

  const safeName = (element) =>
    isSecret(element)
      ? element.getAttribute("aria-label") ||
        labelText(element) ||
        element.getAttribute("placeholder") ||
        ""
      : nameOf(element);

  return {
    state,
    refFor,
    elementFor,
    visible,
    clean,
    isField,
    formOf,
    formFields,
    isPasswordField,
    isPayment,
    isSecret,
    isFilled,
    isSubmitter,
    isButtonLike,
    labelText,
    safeName,
  };
}

export function snapshot(kit, { maxChars }) {
  const INTERACTIVE =
    "a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],[role=textbox],[contenteditable=true],[tabindex]:not([tabindex='-1'])";
  const TEXT = "h1,h2,h3,h4,h5,h6,p,li,td,th,label,dt,dd,figcaption,blockquote";
  const TRUNCATED = "… snapshot truncated";
  const VALUELESS = [
    "hidden",
    "checkbox",
    "radio",
    "submit",
    "button",
    "reset",
    "image",
  ];

  for (const [ref, weak] of kit.state.byRef) {
    if (!weak.deref()) kit.state.byRef.delete(ref);
  }

  const lines = [];
  let size = 0;
  let truncated = false;
  const push = (line) => {
    const room = maxChars - TRUNCATED.length - 1 - size;
    if (room <= 0) {
      truncated = true;
      return false;
    }
    const text = line.length > room ? line.slice(0, room) : line;
    lines.push(text);
    size += text.length + 1;
    if (text.length < line.length) truncated = true;
    return !truncated;
  };

  const describe = (element) => {
    const role = element.getAttribute("role") || element.tagName.toLowerCase();
    const parts = [`[${kit.refFor(element)}]`, role];
    const text = kit.clean(kit.safeName(element), 120);
    if (text) parts.push(JSON.stringify(text));
    if (kit.isField(element)) {
      if (element.type) parts.push(`type=${element.type}`);
      if (element.name) parts.push(`name=${element.name}`);
      if (element.placeholder) {
        parts.push(
          `placeholder=${JSON.stringify(kit.clean(element.placeholder, 60))}`,
        );
      }
      if (kit.isSecret(element)) {
        parts.push(element.value ? "value=<hidden>" : "empty");
      } else if (element.value && !VALUELESS.includes(element.type)) {
        parts.push(`value=${JSON.stringify(kit.clean(element.value, 80))}`);
      }
    }
    if (
      element instanceof HTMLInputElement &&
      (element.type === "checkbox" || element.type === "radio")
    ) {
      parts.push(element.checked ? "checked" : "unchecked");
    }
    for (const name of ["checked", "selected", "expanded", "pressed"]) {
      const value = element.getAttribute(`aria-${name}`);
      if (value === "true" || value === "false" || value === "mixed") {
        parts.push(`${name}=${value}`);
      }
    }
    if (element.disabled || element.getAttribute("aria-disabled") === "true") {
      parts.push("disabled");
    }
    if (element instanceof HTMLAnchorElement && element.href) {
      parts.push(`href=${kit.clean(element.href, 120)}`);
    }
    return parts.join(" ");
  };

  push(`url: ${location.href}`);
  push(`title: ${kit.clean(document.title, 200)}`);
  const seen = new Set();
  for (const element of document.querySelectorAll(`${INTERACTIVE},${TEXT}`)) {
    if (seen.has(element) || !kit.visible(element)) continue;
    seen.add(element);
    if (element.matches(INTERACTIVE)) {
      if (!push(describe(element))) break;
      continue;
    }
    if (element.closest(INTERACTIVE)) continue;
    const text = kit.clean(element.innerText, 200);
    if (text && !push(`${element.tagName.toLowerCase()}: ${text}`)) break;
  }
  if (truncated) lines.push(TRUNCATED);
  return lines.join("\n");
}

export function rect(kit, { ref, forClick }) {
  const element = kit.elementFor(ref);
  if (!element) return null;
  element.scrollIntoView({ block: "center", inline: "center" });
  const box = element.getBoundingClientRect();
  if (box.width === 0 || box.height === 0 || !kit.visible(element)) {
    return { problem: "hidden" };
  }
  const x = box.left + box.width / 2;
  const y = box.top + box.height / 2;
  if (forClick) {
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) {
      return { problem: "covered" };
    }
    const target = document.elementFromPoint(x, y);
    const reaches =
      target &&
      (target === element ||
        element.contains(target) ||
        target.closest?.("label")?.control === element);
    if (!reaches) return { problem: "covered" };
  }
  return {
    x,
    y,
    width: box.width,
    height: box.height,
    left: box.left,
    top: box.top,
  };
}

export function focus(kit, { ref, clear }) {
  const element = kit.elementFor(ref);
  if (!element) return false;
  element.scrollIntoView({ block: "center" });
  element.focus();
  if (clear && "value" in element) {
    element.select?.();
  } else if (clear && element.isContentEditable) {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  } else if (
    "setSelectionRange" in element &&
    typeof element.value === "string"
  ) {
    try {
      element.setSelectionRange(element.value.length, element.value.length);
    } catch {}
  }
  return document.activeElement === element;
}

export function findText(kit, { text }) {
  const ACTIONABLE =
    "a[href],button,input,select,textarea,summary,label,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch]";
  const LABELLED =
    "input:not([type=hidden]),textarea,select,img,[aria-label],[title]";
  const MAX_TEXT_NODES = 5000;
  const needle = text.toLowerCase();

  const fieldText = (element) =>
    [
      element.getAttribute("aria-label"),
      element.getAttribute("placeholder"),
      element.getAttribute("title"),
      element.getAttribute("alt"),
      kit.isButtonLike(element) ? element.value : "",
      kit.labelText(element),
    ]
      .filter(Boolean)
      .join(" ");

  for (const field of document.querySelectorAll(LABELLED)) {
    if (
      kit.visible(field) &&
      kit.clean(fieldText(field), 400).toLowerCase().includes(needle)
    ) {
      return kit.refFor(field);
    }
  }

  for (const element of document.querySelectorAll(ACTIONABLE)) {
    if (
      kit.visible(element) &&
      kit.clean(element.innerText, 400).toLowerCase().includes(needle)
    ) {
      return kit.refFor(element);
    }
  }

  const walker = document.createTreeWalker(
    document.body || document.documentElement,
    NodeFilter.SHOW_TEXT,
  );
  let fallback = null;
  let node = walker.nextNode();
  for (
    let seen = 0;
    node && seen < MAX_TEXT_NODES;
    seen++, node = walker.nextNode()
  ) {
    if (!(node.nodeValue || "").toLowerCase().includes(needle)) continue;
    const parent = node.parentElement;
    if (!parent || !kit.visible(parent)) continue;
    const actionable = parent.closest(ACTIONABLE);
    if (actionable && kit.visible(actionable)) return kit.refFor(actionable);
    fallback ??= parent;
  }
  return fallback ? kit.refFor(fallback) : null;
}

export function sensitivity(kit, { ref }) {
  const DESTRUCTIVE =
    /delete|remove|destroy|purchase|buy|pay|confirm|transfer|revoke/i;
  const element = kit.elementFor(ref);
  if (!element) return null;
  const form = kit.formOf(element);
  const fields = form ? kit.formFields(form) : [element];
  const label = kit.clean(
    kit.safeName(element) || element.getAttribute("placeholder") || "",
    80,
  );
  return {
    typesPassword: kit.isPasswordField(element),
    password: fields.some(kit.isPasswordField),
    payment: fields.some(kit.isPayment),
    submitsData:
      kit.isSubmitter(element) && !!form && fields.some(kit.isFilled),
    destructive: DESTRUCTIVE.test(label),
    label,
  };
}

export function focusedForm(kit) {
  const element = document.activeElement;
  if (!element) return null;
  const form = kit.formOf(element);
  const fields = form
    ? kit.formFields(form)
    : kit.isField(element)
      ? [element]
      : null;
  if (!fields) return null;
  return {
    password: fields.some(kit.isPasswordField),
    payment: fields.some(kit.isPayment),
    filled: fields.some(kit.isFilled),
  };
}
