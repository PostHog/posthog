interface BabelLike {
  transform: (
    code: string,
    options: Record<string, unknown>,
  ) => { code?: string | null };
}

interface BabelTypes {
  jsxAttribute: (name: unknown, value: unknown) => unknown;
  jsxIdentifier: (name: string) => unknown;
  stringLiteral: (value: string) => unknown;
}

interface JsxElementPath {
  node: {
    start?: number | null;
    end?: number | null;
    openingElement: {
      name: { type: string; name?: string; property?: { name?: string } };
      attributes: unknown[];
    };
  };
  findParent: (test: (parent: ParentPath) => boolean) => unknown;
}

interface ParentPath {
  isCallExpression: () => boolean;
  node: { callee: { type: string; property?: { name?: string } } };
}

interface ModulePath {
  node: { source?: { value: unknown } | null };
}

interface CompileOptions {
  editing: boolean;
  basePlugins: unknown[];
  cache: Map<string, string>;
}

export function compileCanvasProject(
  Babel: BabelLike,
  files: Record<string, string>,
  entry: string,
  options: CompileOptions,
): string {
  const urls = new Map<string, string>();
  const extensions = [
    "",
    ".tsx",
    ".ts",
    ".jsx",
    ".js",
    "/index.tsx",
    "/index.ts",
  ];

  const normalize = (parts: string[]): string => {
    const out: string[] = [];
    for (const part of parts) {
      if (part === "" || part === ".") continue;
      if (part === "..") out.pop();
      else out.push(part);
    }
    return out.join("/");
  };

  const resolve = (from: string, specifier: string): string | null => {
    const base = from.split("/").slice(0, -1);
    const joined = normalize([...base, ...specifier.split("/")]);
    for (const extension of extensions) {
      const candidate = joined + extension;
      if (candidate in files) return candidate;
    }
    return null;
  };

  const blobUrl = (code: string): string => {
    const cached = options.cache.get(code);
    if (cached) return cached;
    const url = URL.createObjectURL(
      new Blob([code], { type: "text/javascript" }),
    );
    options.cache.set(code, url);
    return url;
  };

  const styleModule = (css: string): string => {
    const style = document.createElement("style");
    style.setAttribute("data-canvas-style", "");
    style.textContent = css;
    document.head.appendChild(style);
    return blobUrl("export default null;");
  };

  const sourceRangePlugin =
    (file: string) =>
    ({ types: t }: { types: BabelTypes }) => ({
      visitor: {
        JSXElement(path: JsxElementPath) {
          const node = path.node;
          if (typeof node.start !== "number" || typeof node.end !== "number")
            return;
          const name = node.openingElement.name;
          const tag =
            name.type === "JSXIdentifier" ? name.name : name.property?.name;
          if (tag === "Fragment") return;
          const repeated = !!path.findParent(
            (parent: ParentPath) =>
              parent.isCallExpression() &&
              parent.node.callee.type === "MemberExpression" &&
              parent.node.callee.property?.name === "map",
          );
          const value = `${file}|${node.start}|${node.end}${repeated ? "|r" : ""}`;
          node.openingElement.attributes.unshift(
            t.jsxAttribute(
              t.jsxIdentifier("data-ph-src"),
              t.stringLiteral(value),
            ),
          );
        },
      },
    });

  const build = (path: string, stack: string[]): string => {
    const known = urls.get(path);
    if (known) return known;
    if (stack.includes(path))
      throw new Error(`Circular import: ${[...stack, path].join(" -> ")}`);
    const source = files[path] ?? "";
    if (path.endsWith(".css")) {
      const url = styleModule(source);
      urls.set(path, url);
      return url;
    }
    if (path.endsWith(".json")) {
      const url = blobUrl(`export default ${source.trim() || "null"};`);
      urls.set(path, url);
      return url;
    }
    const rewriteImports = () => ({
      visitor: {
        "ImportDeclaration|ExportNamedDeclaration|ExportAllDeclaration"(
          nodePath: ModulePath,
        ) {
          const sourceNode = nodePath.node.source;
          if (!sourceNode || typeof sourceNode.value !== "string") return;
          if (!sourceNode.value.startsWith(".")) return;
          const resolved = resolve(path, sourceNode.value);
          if (!resolved)
            throw new Error(
              `Cannot find "${sourceNode.value}" imported from ${path}`,
            );
          sourceNode.value = build(resolved, [...stack, path]);
        },
      },
    });
    const plugins = [
      ...options.basePlugins,
      rewriteImports,
      ...(options.editing && !path.startsWith("src/blocks/")
        ? [sourceRangePlugin(path)]
        : []),
    ];
    const out = Babel.transform(source, {
      filename: path.split("/").pop(),
      plugins,
      presets: [
        ["react", { runtime: "automatic" }],
        [
          "typescript",
          { isTSX: true, allExtensions: true, onlyRemoveTypeImports: true },
        ],
      ],
    }).code;
    const url = blobUrl(out ?? "");
    urls.set(path, url);
    return url;
  };

  for (const style of Array.from(
    document.querySelectorAll("style[data-canvas-style]"),
  )) {
    style.remove();
  }
  return build(entry, []);
}

type Post = (message: Record<string, unknown>) => void;

export function installCanvasEditing(
  post: Post,
  labels: Record<string, string>,
) {
  const PRIMARY = "#f54e00";
  let enabled = false;
  let rev = 0;
  let hovered: HTMLElement | null = null;
  let selected: HTMLElement | null = null;
  let selectedBlockId: string | null = null;
  let selectedSource: { key: string; block: string | null } | null = null;
  let dragOrigin: { x: number; y: number; element: HTMLElement } | null = null;
  let frame = 0;

  const EASE_OUT = "cubic-bezier(0.23, 1, 0.32, 1)";
  const EASE_IN_OUT = "cubic-bezier(0.77, 0, 0.175, 1)";
  const reduceMotion = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const layer = document.createElement("div");
  layer.style.cssText =
    "position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
  const hoverBox = document.createElement("div");
  const selectBox = document.createElement("div");
  const label = document.createElement("div");
  const line = document.createElement("div");
  hoverBox.style.cssText = `position:fixed;left:0;top:0;border:1px solid rgba(245,78,0,.45);border-radius:8px;opacity:0;transition:opacity 100ms ease;`;
  selectBox.style.cssText = `position:fixed;left:0;top:0;border:1.5px solid ${PRIMARY};border-radius:10px;opacity:0;box-shadow:0 0 0 3px rgba(245,78,0,.08);transition:opacity 120ms ease;`;
  label.style.cssText = `position:fixed;left:0;top:0;background:${PRIMARY};color:#fff;font:600 10.5px/18px system-ui,sans-serif;padding:0 7px;border-radius:5px 5px 0 0;opacity:0;white-space:nowrap;transition:opacity 120ms ease;`;
  line.style.cssText = `position:fixed;left:0;top:0;background:${PRIMARY};border-radius:99px;opacity:0;transition:opacity 120ms ease,transform 110ms ${EASE_OUT};`;
  const emptyHint = document.createElement("div");
  emptyHint.textContent = "Drop blocks here, or click one in the panel";
  emptyHint.style.cssText =
    "position:fixed;display:flex;align-items:center;justify-content:center;border:1.5px dashed rgba(128,128,128,.35);border-radius:12px;color:rgba(128,128,128,.95);font:500 13px/1.4 system-ui,sans-serif;opacity:0;transition:opacity 160ms;";
  layer.append(emptyHint, hoverBox, selectBox, label, line);

  const parseSource = (element: Element) => {
    const raw = element.getAttribute("data-ph-src");
    if (!raw) return null;
    const [file, start, end, flag] = raw.split("|");
    if (!file) return null;
    return {
      file,
      start: Number(start),
      end: Number(end),
      repeated: flag === "r",
    };
  };

  let openBlock: Element | null = null;

  const candidateOf = (start: Element | null): HTMLElement | null => {
    let element: Element | null = start;
    while (element && element !== document.body) {
      const blockRoot = element.closest("[data-ph-block]");
      if (
        blockRoot instanceof HTMLElement &&
        blockRoot !== openBlock &&
        blockRoot.hasAttribute("data-ph-src")
      )
        return blockRoot;
      const source = parseSource(element);
      const rect = element.getBoundingClientRect();
      if (source && !source.repeated && rect.width >= 24 && rect.height >= 12) {
        return element as HTMLElement;
      }
      element = element.parentElement;
    }
    return null;
  };

  const gridSourceOf = (element: HTMLElement) => {
    const parent = element.parentElement;
    if (!parent || !getComputedStyle(parent).display.includes("grid"))
      return null;
    const source = parseSource(parent);
    if (!source || source.repeated) return null;
    return { file: source.file, start: source.start, end: source.end };
  };

  const fullGridRow = (element: HTMLElement) => {
    const grid = gridSourceOf(element);
    const parent = element.parentElement;
    if (!grid || !parent) return null;
    const columns = getComputedStyle(parent)
      .gridTemplateColumns.split(" ")
      .filter(Boolean).length;
    if (columns < 2 || columns >= 4 || parent.children.length !== columns)
      return null;
    return { ...grid, columns };
  };

  const describe = (element: HTMLElement) => {
    const source = parseSource(element);
    const blockType = element.getAttribute("data-ph-block");
    let props: Record<string, unknown> = {};
    try {
      props = JSON.parse(element.getAttribute("data-ph-props") ?? "{}");
    } catch {
      props = {};
    }
    const onlyText =
      element.children.length === 0 ? (element.textContent ?? "") : null;
    return {
      rev,
      source: source
        ? { file: source.file, start: source.start, end: source.end }
        : null,
      blockType,
      blockId: element.getAttribute("data-ph-block-id"),
      props,
      tag: element.tagName.toLowerCase(),
      text: onlyText,
      params: element.getAttribute("data-ph-params"),
      layout: {
        inGrid:
          !!element.parentElement &&
          getComputedStyle(element.parentElement).display.includes("grid"),
        grow: fullGridRow(element),
        grid: gridSourceOf(element),
      },
    };
  };

  const place = (box: HTMLElement, element: HTMLElement | null, inset = 0) => {
    if (!element || !element.isConnected) {
      box.style.opacity = "0";
      return;
    }
    const rect = element.getBoundingClientRect();
    box.style.transform = `translate3d(${rect.left - inset}px, ${rect.top - inset}px, 0)`;
    box.style.width = `${rect.width + inset * 2}px`;
    box.style.height = `${rect.height + inset * 2}px`;
    box.style.opacity = "1";
  };

  const labelFor = (element: HTMLElement): string => {
    const block = element.getAttribute("data-ph-block");
    if (!block) return labels[element.tagName.toLowerCase()] ?? "Element";
    const spaced = block.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
    return labels[block] ?? spaced.charAt(0) + spaced.slice(1).toLowerCase();
  };

  const paintEmptyHint = () => {
    const rootElement = document.getElementById("root")
      ?.firstElementChild as HTMLElement | null;
    const last = rootElement?.lastElementChild;
    const empty = enabled && !!rootElement && rootElement.children.length <= 1;
    if (!empty || !rootElement) {
      emptyHint.style.opacity = "0";
      return;
    }
    const style = getComputedStyle(rootElement);
    const box = rootElement.getBoundingClientRect();
    const left = box.left + Number.parseFloat(style.paddingLeft);
    const width =
      box.width -
      Number.parseFloat(style.paddingLeft) -
      Number.parseFloat(style.paddingRight);
    const top = (last ? last.getBoundingClientRect().bottom : box.top) + 24;
    emptyHint.style.left = `${left}px`;
    emptyHint.style.top = `${top}px`;
    emptyHint.style.width = `${width}px`;
    emptyHint.style.height = "180px";
    emptyHint.style.opacity = "1";
  };

  const paint = () => {
    place(hoverBox, hovered && hovered !== selected ? hovered : null, 3);
    place(selectBox, selected, 4);
    if (selected?.isConnected) {
      const rect = selected.getBoundingClientRect();
      label.textContent = labelFor(selected);
      label.style.transform = `translate3d(${rect.left - 4}px, ${rect.top - 22}px, 0)`;
      label.style.opacity = "1";
    } else {
      label.style.opacity = "0";
    }
    paintEmptyHint();
    frame = requestAnimationFrame(paint);
  };

  const remember = (element: HTMLElement | null) => {
    selected = element;
    selectedBlockId = element?.getAttribute("data-ph-block-id") ?? null;
    const source = element ? parseSource(element) : null;
    selectedSource = source
      ? {
          key: `${source.file}|${source.start}`,
          block: element?.getAttribute("data-ph-block") ?? null,
        }
      : null;
  };

  const select = (element: HTMLElement | null) => {
    remember(element);
    post({
      type: "canvas-edit-select",
      element: element ? describe(element) : null,
      byPointer: true,
    });
  };

  const axisOf = (element: HTMLElement): "row" | "column" => {
    const parent = element.parentElement;
    if (!parent) return "column";
    const style = getComputedStyle(parent);
    if (style.display.includes("flex"))
      return style.flexDirection.startsWith("row") ? "row" : "column";
    if (style.display.includes("grid")) {
      const top = element.getBoundingClientRect().top;
      const siblings = Array.from(parent.children).filter(
        (child) => child !== element,
      );
      const sameRow = siblings.some(
        (sibling) => Math.abs(sibling.getBoundingClientRect().top - top) < 6,
      );
      return sameRow ? "row" : "column";
    }
    return "column";
  };

  const nearestChild = (
    container: HTMLElement,
    x: number,
    y: number,
  ): HTMLElement | null => {
    let best: HTMLElement | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const child of Array.from(container.children)) {
      const candidate = candidateOf(child);
      if (
        !candidate ||
        candidate === container ||
        !container.contains(candidate)
      )
        continue;
      const rect = candidate.getBoundingClientRect();
      const dx = Math.max(rect.left - x, 0, x - rect.right);
      const dy = Math.max(rect.top - y, 0, y - rect.bottom);
      const distance = Math.hypot(dx, dy);
      if (distance < bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    }
    return best;
  };

  const isBox = (element: HTMLElement) => {
    const style = getComputedStyle(element);
    const bordered =
      Number.parseFloat(style.borderTopWidth) > 0 &&
      Number.parseFloat(style.borderBottomWidth) > 0;
    const filled =
      style.backgroundColor !== "rgba(0, 0, 0, 0)" &&
      style.backgroundColor !== "transparent";
    return (
      (bordered || filled) && Number.parseFloat(style.borderTopLeftRadius) > 0
    );
  };

  const coarseTarget = (element: HTMLElement, root: HTMLElement | null) => {
    let current: HTMLElement | null = element;
    while (current && current !== root) {
      const tall = current.getBoundingClientRect().height >= 100;
      if (current.hasAttribute("data-ph-block") || (tall && isBox(current)))
        return current;
      const parent = candidateOf(current.parentElement);
      if (!parent || parent === current) break;
      current = parent;
    }
    let fallback: HTMLElement = element;
    while (fallback !== root && fallback.getBoundingClientRect().height < 100) {
      const parent = candidateOf(fallback.parentElement);
      if (!parent || parent === fallback) break;
      fallback = parent;
    }
    return fallback;
  };

  const findDropTarget = (
    x: number,
    y: number,
    exclude: string | null,
    coarse: boolean,
  ) => {
    let target = candidateOf(document.elementFromPoint(x, y));
    const root = candidateOf(
      document.getElementById("root")?.firstElementChild ?? null,
    );
    if (!target) target = root;
    if (!target) return null;
    if (coarse) target = coarseTarget(target, root);
    const rect = target.getBoundingClientRect();
    const layout = getComputedStyle(target).display;
    const arrangesChildren =
      layout.includes("grid") || layout.includes("flex") || rect.height > 160;
    const atomic = coarse && target !== root && isBox(target);
    const isContainer =
      target === root ||
      (!atomic &&
        target.children.length > 1 &&
        !target.hasAttribute("data-ph-block") &&
        arrangesChildren);
    if (isContainer) {
      const child = nearestChild(target, x, y);
      if (child) target = child;
    }
    const source = parseSource(target);
    if (!source) return null;
    if (exclude) {
      const [file, start, end] = exclude.split("|");
      if (
        source.file === file &&
        source.start >= Number(start) &&
        source.end <= Number(end)
      )
        return null;
    }
    const box = target.getBoundingClientRect();
    const axis = axisOf(target);
    let position: "before" | "after" | "left" | "right";
    let indicator: { left: number; top: number; width: number; height: number };
    const edge = Math.min(64, box.width * 0.2);
    if (axis === "column" && box.width > 240 && x < box.left + edge)
      position = "left";
    else if (axis === "column" && box.width > 240 && x > box.right - edge)
      position = "right";
    else if (axis === "row")
      position = x < box.left + box.width / 2 ? "before" : "after";
    else position = y < box.top + box.height / 2 ? "before" : "after";
    const vertical =
      axis === "row" || position === "left" || position === "right";
    if (vertical) {
      const atStart = position === "before" || position === "left";
      indicator = {
        left: atStart ? box.left - 9 : box.right + 7,
        top: box.top,
        width: 2,
        height: box.height,
      };
    } else {
      indicator = {
        left: box.left,
        top: position === "before" ? box.top - 9 : box.bottom + 7,
        width: box.width,
        height: 2,
      };
    }
    const grow =
      position === "before" || position === "after"
        ? fullGridRow(target)
        : null;
    return {
      rev,
      target: {
        file: source.file,
        start: source.start,
        end: source.end,
        place: position,
        ...(grow ? { grow } : {}),
      },
      indicator,
    };
  };

  const dropTarget = (
    x: number,
    y: number,
    exclude: string | null,
    coarse: boolean,
  ) => {
    const rootElement = document.getElementById("root")?.firstElementChild;
    openBlock = rootElement?.hasAttribute("data-ph-block") ? rootElement : null;
    try {
      return findDropTarget(x, y, exclude, coarse);
    } finally {
      openBlock = null;
    }
  };

  const showLine = (
    indicator: {
      left: number;
      top: number;
      width: number;
      height: number;
    } | null,
  ) => {
    if (!indicator) {
      line.style.opacity = "0";
      return;
    }
    const wasHidden = line.style.opacity !== "1";
    if (wasHidden) line.style.transition = "none";
    line.style.transform = `translate3d(${indicator.left}px, ${indicator.top}px, 0)`;
    line.style.width = `${indicator.width}px`;
    line.style.height = `${indicator.height}px`;
    if (wasHidden) {
      void line.offsetWidth;
      line.style.transition = `opacity 120ms ease, transform 110ms ${EASE_OUT}`;
    }
    line.style.opacity = "1";
  };

  let forwarding = false;
  let lifted: HTMLElement | null = null;
  const drop = () => {
    if (!lifted) return;
    lifted.style.removeProperty("opacity");
    lifted.style.removeProperty("transition");
    lifted = null;
  };

  const onMove = (event: MouseEvent) => {
    if (!enabled) return;
    const pressed = (event.buttons & 1) === 1;
    if (forwarding) {
      if (!pressed) {
        forwarding = false;
        drop();
        post({ type: "canvas-edit-pointer-cancel" });
        return;
      }
      post({ type: "canvas-edit-pointer", x: event.clientX, y: event.clientY });
      return;
    }
    if (dragOrigin && !pressed) dragOrigin = null;
    hovered = candidateOf(event.target as Element);
    if (
      dragOrigin &&
      Math.hypot(event.clientX - dragOrigin.x, event.clientY - dragOrigin.y) > 5
    ) {
      const described = describe(dragOrigin.element);
      lifted = dragOrigin.element;
      lifted.style.transition = "opacity 120ms";
      lifted.style.opacity = "0.35";
      dragOrigin = null;
      forwarding = true;
      hovered = null;
      post({
        type: "canvas-edit-drag-start",
        element: described,
        x: event.clientX,
        y: event.clientY,
      });
    }
  };

  const TEXT_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "span",
    "li",
    "small",
    "strong",
    "em",
    "label",
    "td",
    "th",
    "blockquote",
    "figcaption",
  ];
  let editingText: { element: HTMLElement; original: string } | null = null;

  const finishText = (commit: boolean) => {
    const current = editingText;
    if (!current) return;
    editingText = null;
    const { element, original } = current;
    const text = (element.textContent ?? "").replace(/\s+/g, " ").trim();
    element.removeAttribute("contenteditable");
    element.style.removeProperty("outline");
    element.style.removeProperty("cursor");
    if (!commit || !text || text === original.trim()) {
      element.textContent = original;
      return;
    }
    post({ type: "canvas-edit-text", element: describe(element), text });
  };

  const startText = (element: HTMLElement) => {
    const plain =
      !element.hasAttribute("data-ph-block") &&
      element.children.length === 0 &&
      TEXT_TAGS.includes(element.tagName.toLowerCase());
    if (!plain) return false;
    editingText = { element, original: element.textContent ?? "" };
    element.setAttribute("contenteditable", "plaintext-only");
    element.style.outline = "none";
    element.style.cursor = "text";
    element.focus();
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    element.addEventListener("blur", () => finishText(true), { once: true });
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        element.blur();
      }
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        finishText(false);
        element.blur();
      }
    });
    return true;
  };

  const onDouble = (event: MouseEvent) => {
    if (!enabled) return;
    event.preventDefault();
    event.stopPropagation();
    const element = candidateOf(event.target as Element);
    if (element && element !== editingText?.element) startText(element);
  };

  const onDown = (event: MouseEvent) => {
    forwarding = false;
    if (!enabled || event.button !== 0) return;
    if (editingText?.element.contains(event.target as Node)) return;
    const element = candidateOf(event.target as Element);
    event.preventDefault();
    event.stopPropagation();
    if (!element) {
      select(null);
      return;
    }
    select(element);
    const isRoot =
      element ===
      candidateOf(document.getElementById("root")?.firstElementChild ?? null);
    if (!isRoot) dragOrigin = { x: event.clientX, y: event.clientY, element };
  };

  const swallow = (event: Event) => {
    if (!enabled) return;
    event.preventDefault();
    event.stopPropagation();
  };

  const onUp = (_event: MouseEvent) => {
    dragOrigin = null;
    if (!forwarding) return;
    forwarding = false;
    post({
      type: "canvas-edit-pointer-up",
    });
  };

  const onKey = (event: KeyboardEvent) => {
    if (!enabled) return;
    const target = event.target as HTMLElement | null;
    if (
      target &&
      (target.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
    )
      return;
    if (
      ["Backspace", "Delete", "Escape"].includes(event.key) ||
      ((event.metaKey || event.ctrlKey) &&
        ["d", "z"].includes(event.key.toLowerCase()))
    ) {
      event.preventDefault();
      post({
        type: "canvas-edit-key",
        key: event.key,
        metaKey: event.metaKey,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
      });
    }
  };

  const land = (element: HTMLElement) => {
    const keyframes = reduceMotion()
      ? [{ opacity: 0 }, { opacity: 1 }]
      : [
          { opacity: 0, transform: "scale(0.985)" },
          { opacity: 1, transform: "none" },
        ];
    element.animate(keyframes, { duration: 240, easing: EASE_OUT });
  };

  let captured = new Map<string, DOMRect>();

  const capture = () => {
    captured = new Map();
    for (const element of Array.from(
      document.querySelectorAll<HTMLElement>("[data-ph-block-id]"),
    )) {
      const id = element.getAttribute("data-ph-block-id");
      if (id) captured.set(id, element.getBoundingClientRect());
    }
  };

  const slideIntoPlace = (): Map<string, DOMRect> => {
    const before = captured;
    captured = new Map();
    if (reduceMotion() || before.size === 0) return before;
    for (const element of Array.from(
      document.querySelectorAll<HTMLElement>("[data-ph-block-id]"),
    )) {
      const id = element.getAttribute("data-ph-block-id");
      const previous = id ? before.get(id) : undefined;
      if (!previous) continue;
      const now = element.getBoundingClientRect();
      const dx = previous.left - now.left;
      const dy = previous.top - now.top;
      const resized =
        Math.abs(previous.width - now.width) > 2 ||
        Math.abs(previous.height - now.height) > 2;
      if (resized || (Math.abs(dx) < 1 && Math.abs(dy) < 1)) continue;
      element.animate(
        [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
        { duration: 300, easing: EASE_IN_OUT },
      );
    }
    return before;
  };

  const afterMount = (
    nextRev: number,
    focusBlockId: string | null,
    focusSource: string | null,
    attempt = 0,
  ) => {
    rev = nextRev;
    hovered = null;
    const rootElement = candidateOf(
      document.getElementById("root")?.firstElementChild ?? null,
    );
    if (!rootElement && attempt < 120) {
      requestAnimationFrame(() => {
        if (rev === nextRev)
          afterMount(nextRev, focusBlockId, focusSource, attempt + 1);
      });
      return;
    }
    const previousRects = slideIntoPlace();
    const rootSource = rootElement ? parseSource(rootElement) : null;
    post({
      type: "canvas-edit-root",
      rev,
      root: rootSource
        ? {
            file: rootSource.file,
            start: rootSource.start,
            end: rootSource.end,
          }
        : null,
    });
    const id = focusBlockId ?? selectedBlockId;
    const sourceAt = (key: string) =>
      document.querySelector(`[data-ph-src^="${CSS.escape(`${key}|`)}"]`);
    const previous = selectedSource ? sourceAt(selectedSource.key) : null;
    const sameBlock =
      previous?.getAttribute("data-ph-block") === selectedSource?.block;
    const bySource = focusSource
      ? sourceAt(focusSource)
      : sameBlock
        ? previous
        : null;
    const element = id
      ? document.querySelector(`[data-ph-block-id="${CSS.escape(id)}"]`)
      : bySource;
    if (element instanceof HTMLElement) {
      remember(element);
      post({ type: "canvas-edit-select", element: describe(element) });
      const arrived =
        !!focusBlockId && !focusSource && !previousRects.has(focusBlockId);
      if (arrived) land(element);
    } else {
      remember(null);
      post({ type: "canvas-edit-select", element: null });
    }
  };

  const setEnabled = (next: boolean) => {
    if (next === enabled) return;
    enabled = next;
    if (enabled) {
      document.body.appendChild(layer);
      document.documentElement.style.cursor = "default";
      frame = requestAnimationFrame(paint);
    } else {
      layer.remove();
      cancelAnimationFrame(frame);
      selected = null;
      hovered = null;
    }
  };

  window.addEventListener("mousemove", onMove, true);
  window.addEventListener("mousedown", onDown, true);
  window.addEventListener("mouseup", onUp, true);
  window.addEventListener("click", swallow, true);
  window.addEventListener("dblclick", onDouble, true);
  window.addEventListener("keydown", onKey, true);
  document.addEventListener("mouseleave", () => {
    hovered = null;
  });

  return {
    capture,
    setEnabled,
    afterMount,
    handle(message: Record<string, unknown>) {
      if (message.type === "canvas-edit-drag-move") {
        const hit = enabled
          ? dropTarget(
              Number(message.x),
              Number(message.y),
              (message.exclude as string | null) ?? null,
              message.coarse === true,
            )
          : null;
        showLine(hit?.indicator ?? null);
        post({
          type: "canvas-edit-drop-target",
          hit: hit ? { rev: hit.rev, target: hit.target } : null,
        });
        return true;
      }
      if (message.type === "canvas-edit-drag-end") {
        if (message.final === true) {
          forwarding = false;
          dragOrigin = null;
          drop();
        }
        showLine(null);
        return true;
      }
      if (message.type === "canvas-edit-deselect") {
        remember(null);
        return true;
      }
      return false;
    },
  };
}
