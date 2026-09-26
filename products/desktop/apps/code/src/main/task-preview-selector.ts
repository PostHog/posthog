const PREFERRED_ATTRIBUTES = ["data-attr", "data-testid", "data-test", "name"];
const MAX_DEPTH = 12;

function isUnique(root: ParentNode, selector: string): boolean {
  try {
    return root.querySelectorAll(selector).length === 1;
  } catch {
    return false;
  }
}

function attributeSelector(element: Element): string | null {
  for (const attribute of PREFERRED_ATTRIBUTES) {
    const value = element.getAttribute(attribute);
    if (!value) continue;
    const selector = `${element.tagName.toLowerCase()}[${attribute}="${CSS.escape(value)}"]`;
    if (isUnique(element.ownerDocument, selector)) return selector;
  }
  return null;
}

function idSelector(element: Element): string | null {
  if (!element.id) return null;
  const selector = `#${CSS.escape(element.id)}`;
  return isUnique(element.ownerDocument, selector) ? selector : null;
}

function nthOfType(element: Element): string {
  const tag = element.tagName.toLowerCase();
  const parent = element.parentElement;
  if (!parent) return tag;
  const siblings = Array.from(parent.children).filter(
    (child) => child.tagName === element.tagName,
  );
  if (siblings.length === 1) return tag;
  return `${tag}:nth-of-type(${siblings.indexOf(element) + 1})`;
}

export function uniqueSelector(element: Element): string {
  const direct = idSelector(element) ?? attributeSelector(element);
  if (direct) return direct;

  const parts: string[] = [];
  let current: Element | null = element;
  for (let depth = 0; current && depth < MAX_DEPTH; depth += 1) {
    if (current !== element) {
      const anchor = idSelector(current) ?? attributeSelector(current);
      if (anchor) {
        parts.unshift(anchor);
        break;
      }
    }
    if (current.tagName === "BODY" || current.tagName === "HTML") {
      parts.unshift(current.tagName.toLowerCase());
      break;
    }
    parts.unshift(nthOfType(current));
    const candidate = parts.join(" > ");
    if (isUnique(element.ownerDocument, candidate)) return candidate;
    current = current.parentElement;
  }
  return parts.join(" > ");
}
