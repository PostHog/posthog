import {
  buildImportMap,
  FREEFORM_BABEL_URL,
  FREEFORM_ESM_HOST,
  FREEFORM_QUILL_CSS_URLS,
} from "@posthog/core/canvas/freeformWhitelist";
import {
  CANVAS_SDK_SPECIFIER,
  CANVAS_V2_CHANNEL,
  CANVAS_V2_FIELD_MAX_ENTRIES,
  CANVAS_V2_MAX_STATE_VALUE_BYTES,
} from "@posthog/shared";
import {
  decodeJsxUnicodeEscapes,
  resolveExternalAnchorUrl,
} from "@posthog/ui/features/canvas/freeform/sandboxRuntime";
import {
  SHARED_FIELD_READ_ONLY_STATE,
  SHARED_TEXT_FULL,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";

// Builds the HTML document for the Canvases v2 board frame: one null-origin
// iframe (sandbox="allow-scripts") that hosts every fragment of a board. The
// host page never interpolates fragment code into this document; fragments
// arrive over postMessage and run from Blob module URLs.

const TAILWIND_V4 = `<script type="module" src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.1"></script>
<style type="text/tailwindcss">
@import "tailwindcss";
@custom-variant dark (&:where(.dark, .dark *));
@theme inline {
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chrome: var(--chrome);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-success: var(--success);
  --color-success-foreground: var(--success-foreground);
  --color-warning: var(--warning);
  --color-warning-foreground: var(--warning-foreground);
  --color-info: var(--info);
  --color-info-foreground: var(--info-foreground);
  --color-fill-hover: var(--fill-hover);
  --color-fill-selected: var(--fill-selected);
  --color-fill-expanded: var(--fill-expanded);
  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);
}
</style>`;

const TAILWIND_CDN = "https://cdn.jsdelivr.net/npm/@tailwindcss/";

// The "@posthog/canvas-sdk" module served to fragments from a Blob URL. It adds
// useSharedState on top of the ph bridge the bootstrap installs on globalThis.
export const BOARD_FRAME_SDK_MODULE_SOURCE = `import {
  createElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
export const ph = globalThis.ph;
export default globalThis.ph;

const TEXT_MAX_CHARS = ${CANVAS_V2_FIELD_MAX_ENTRIES};
const TEXT_FULL_MESSAGE = ${JSON.stringify(SHARED_TEXT_FULL)};
const CARET_MIN_INTERVAL_MS = 120;
const MIRROR_STYLES = [
  "fontFamily",
  "fontSize",
  "fontWeight",
  "fontStyle",
  "lineHeight",
  "letterSpacing",
  "wordSpacing",
  "textIndent",
  "tabSize",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
];

const messageOf = (error) =>
  String(error && error.message ? error.message : error);

// A caret sits before the character at its offset, so the id of that character
// keeps the caret in place when somebody types above it.
const idAt = (ids, offset) => {
  if (typeof offset !== "number" || offset < 0) return null;
  return offset < ids.length ? ids[offset] : null;
};
const offsetOf = (ids, id, fallback) => {
  if (id === null || id === undefined) return ids.length;
  const at = ids.indexOf(id);
  return at === -1 ? fallback : at;
};

export function useSharedText(key) {
  const host = useRef({ text: "", ids: [] });
  const queued = useRef(null);
  const busy = useRef(false);
  const pumpRef = useRef(null);
  const [view, setView] = useState({ text: "", ids: [], revision: 0 });
  const [echo, setEcho] = useState("");
  const [limitMessage, setLimitMessage] = useState(null);
  const [carets, setCarets] = useState([]);

  const adopt = useCallback((next) => {
    host.current = next;
    setEcho(next.text);
    setView((last) => ({
      text: next.text,
      ids: next.ids,
      revision: last.revision + 1,
    }));
  }, []);

  useEffect(() => {
    const read = () => {
      const next = globalThis.ph.fields.peekText(key);
      host.current = next;
      if (busy.current || queued.current !== null) return;
      adopt(next);
    };
    read();
    return globalThis.ph.fields.subscribe(key, read);
  }, [key, adopt]);

  useEffect(() => {
    const read = () => setCarets(globalThis.ph.fields.caretsFor(key));
    read();
    return globalThis.ph.fields.subscribeCarets(read);
  }, [key]);

  const pump = useCallback(() => {
    const job = queued.current;
    queued.current = null;
    if (job === null) {
      busy.current = false;
      return;
    }
    busy.current = true;
    const base = host.current;
    globalThis.ph.fields
      .editText(key, {
        base: base.text,
        baseIds: base.ids,
        next: job.next,
        caret: job.caret,
      })
      .then((answer) => {
        host.current = answer;
        if (queued.current !== null) {
          pumpRef.current();
          return;
        }
        busy.current = false;
        adopt(answer);
      })
      .catch((error) => {
        queued.current = null;
        busy.current = false;
        setLimitMessage(messageOf(error));
        adopt(host.current);
      });
  }, [key, adopt]);
  pumpRef.current = pump;

  const setText = useCallback((next, caret) => {
    if (next.length > TEXT_MAX_CHARS) {
      setLimitMessage(TEXT_FULL_MESSAGE);
      return;
    }
    setLimitMessage(null);
    setEcho(next);
    queued.current = { next, caret: caret === undefined ? null : caret };
    if (!busy.current) pumpRef.current();
  }, []);

  const remoteCarets = useMemo(() => {
    const out = [];
    for (const caret of carets) {
      const focus = offsetOf(view.ids, caret.focus, -1);
      if (focus === -1) continue;
      out.push({
        clientId: caret.clientId,
        name: caret.name,
        color: caret.color,
        anchor: offsetOf(view.ids, caret.anchor, focus),
        focus,
      });
    }
    return out;
  }, [carets, view.ids]);

  return {
    text: echo,
    ids: view.ids,
    revision: view.revision,
    setText,
    remoteCarets,
    limitMessage,
  };
}

export function useSharedList(key) {
  const [items, setItems] = useState([]);
  const [limitMessage, setLimitMessage] = useState(null);

  useEffect(() => {
    const read = () => setItems(globalThis.ph.fields.peekList(key));
    read();
    return globalThis.ph.fields.subscribe(key, read);
  }, [key]);

  const edit = useCallback(
    (payload) => {
      globalThis.ph.fields
        .editList(key, payload)
        .then((answer) => {
          setLimitMessage(null);
          setItems(answer.items);
        })
        .catch((error) => setLimitMessage(messageOf(error)));
    },
    [key],
  );

  const insert = useCallback(
    (value, afterId) => {
      let anchor = afterId;
      if (anchor === undefined) {
        const rows = globalThis.ph.fields.peekList(key);
        anchor = rows.length > 0 ? rows[rows.length - 1].id : null;
      }
      edit({ insert: [{ afterId: anchor, value }] });
    },
    [key, edit],
  );
  const remove = useCallback((id) => edit({ remove: [id] }), [edit]);
  const update = useCallback(
    (id, value) => edit({ update: [{ id, value }] }),
    [edit],
  );

  return { items, insert, remove, update, limitMessage };
}

export function SharedTextArea({ keyName, placeholder, className, rows }) {
  const field = useSharedText(keyName);
  const areaRef = useRef(null);
  const mirrorRef = useRef(null);
  const caretIds = useRef({ anchor: null, focus: null });
  const caretSentAt = useRef(0);
  const [bars, setBars] = useState([]);
  const text = field.text;
  const ids = field.ids;
  const revision = field.revision;
  const remoteCarets = field.remoteCarets;
  // The ids belong to the text the host holds. A caret is read only when the
  // box, the value in hand and the ids all agree, because a keystroke still in
  // flight would put the caret on the wrong character.
  const capture = useCallback(() => {
    const el = areaRef.current;
    if (!el || el.value !== text || ids.length !== text.length) return null;
    const caret = { anchor: el.selectionStart, focus: el.selectionEnd };
    caretIds.current = {
      anchor: idAt(ids, caret.anchor),
      focus: idAt(ids, caret.focus),
    };
    return caret;
  }, [ids, text]);

  useLayoutEffect(() => {
    const el = areaRef.current;
    if (!el || document.activeElement !== el) return;
    const anchor = offsetOf(ids, caretIds.current.anchor, el.selectionStart);
    const focus = offsetOf(ids, caretIds.current.focus, el.selectionEnd);
    if (el.selectionStart === anchor && el.selectionEnd === focus) return;
    el.setSelectionRange(anchor, focus);
  }, [revision, ids]);

  useLayoutEffect(() => {
    const el = areaRef.current;
    const mirror = mirrorRef.current;
    if (!el || !mirror) return;
    const style = window.getComputedStyle(el);
    for (const name of MIRROR_STYLES) mirror.style[name] = style[name];
    const node = mirror.firstChild;
    if (!node || remoteCarets.length === 0) {
      setBars([]);
      return;
    }
    const box = mirror.getBoundingClientRect();
    const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) || 16;
    const next = [];
    for (const caret of remoteCarets) {
      const range = document.createRange();
      const at = Math.max(0, Math.min(caret.focus, node.length));
      range.setStart(node, at);
      range.setEnd(node, at);
      const rect = range.getBoundingClientRect();
      next.push({
        clientId: caret.clientId,
        name: caret.name,
        color: caret.color,
        left: rect.left - box.left - el.scrollLeft,
        top: rect.top - box.top - el.scrollTop,
        height: rect.height || line,
      });
    }
    setBars(next);
  }, [remoteCarets, text]);

  const reportCaret = useCallback(() => {
    const caret = capture();
    if (caret === null) return;
    const now = Date.now();
    if (now - caretSentAt.current < CARET_MIN_INTERVAL_MS) return;
    caretSentAt.current = now;
    field.setText(text, caret);
  }, [capture, field, text]);

  return createElement(
    "div",
    { className: "relative h-full w-full" + (className ? " " + className : "") },
    createElement("textarea", {
      ref: areaRef,
      value: text,
      rows,
      placeholder,
      spellCheck: false,
      onChange: (event) =>
        field.setText(event.target.value, {
          anchor: event.target.selectionStart,
          focus: event.target.selectionEnd,
        }),
      onSelect: reportCaret,
      onBlur: (event) => field.setText(event.target.value, null),
      className:
        "h-full w-full resize-none rounded-(--radius-sm) border border-border bg-transparent p-2 text-sm leading-relaxed outline-none",
    }),
    createElement(
      "div",
      {
        ref: mirrorRef,
        "aria-hidden": "true",
        className:
          "pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words p-2 text-sm leading-relaxed opacity-0",
      },
      text + "\\u200b",
    ),
    createElement(
      "div",
      { className: "pointer-events-none absolute inset-0 overflow-hidden" },
      bars.map((bar) =>
        createElement(
          "div",
          {
            key: bar.clientId + ":" + bar.top + ":" + bar.left,
            className: "absolute w-[2px]",
            style: {
              left: bar.left,
              top: bar.top,
              height: bar.height,
              background: bar.color,
            },
          },
          createElement(
            "div",
            {
              className:
                "ph-caret-name absolute left-0 whitespace-nowrap rounded-(--radius-sm) px-1 text-[10px] leading-4 text-white",
              style: {
                background: bar.color,
                top: bar.top < 16 ? bar.height + 2 : -16,
              },
            },
            bar.name,
          ),
        ),
      ),
    ),
    field.limitMessage
      ? createElement(
          "div",
          {
            className:
              "absolute inset-x-0 bottom-0 bg-background/90 px-2 py-1 text-[11px] text-destructive",
          },
          field.limitMessage,
        )
      : null,
  );
}

export function useSharedState(key, initial) {
  const read = () => {
    const value = globalThis.ph.state.peek(key);
    return value === null || value === undefined ? initial : value;
  };
  const [value, setValue] = useState(read);
  useEffect(() => {
    setValue(read());
    return globalThis.ph.state.subscribe(key, (next) =>
      setValue(next === null || next === undefined ? initial : next),
    );
  }, [key]);
  const set = useCallback(
    (next) => {
      const resolved = typeof next === "function" ? next(read()) : next;
      return globalThis.ph.state.set(key, resolved);
    },
    [key],
  );
  return [value, set];
}
`;

export function buildBoardFrameDocument(): string {
  const importMap = JSON.stringify(buildImportMap());
  const csp = contentSecurityPolicy();

  const bootstrap = /* js */ `
    import * as Babel from "${FREEFORM_BABEL_URL}";
    const CHANNEL = ${JSON.stringify(CANVAS_V2_CHANNEL)};
    const MAX_STATE_VALUE_BYTES = ${CANVAS_V2_MAX_STATE_VALUE_BYTES};
    const post = (msg) => parent.postMessage({ channel: CHANNEL, ...msg }, "*");
    const world = document.getElementById("world");

    // --- data requests: the only way fragment code reaches PostHog ---
    const pending = new Map();
    let reqSeq = 0;
    const call = (method, payload) =>
      new Promise((resolve, reject) => {
        const id = String(++reqSeq);
        pending.set(id, { resolve, reject });
        post({ type: "data-request", id, method, payload });
      });
    const unavailable = (name) => () =>
      Promise.reject(new Error("ph." + name + " is not available on Canvases v2 yet"));

    // --- shared state: one store per board, mirrored by the host ---
    const stateStore = new Map();
    const subscribers = new Map();
    const jsonOf = (value) => {
      try {
        return JSON.stringify(value === undefined ? null : value) ?? "null";
      } catch {
        return null;
      }
    };
    const peek = (key) => (stateStore.has(key) ? stateStore.get(key) : null);
    const notify = (key, value) => {
      const subs = subscribers.get(key);
      if (!subs) return;
      for (const cb of Array.from(subs)) {
        try {
          cb(value);
        } catch {}
      }
    };
    const writePlain = (key, value) => {
      const next = value === undefined ? null : value;
      if (jsonOf(peek(key)) === jsonOf(next)) return false;
      if (next === null) stateStore.delete(key);
      else stateStore.set(key, next);
      notify(key, next);
      return true;
    };

    // --- mergeable fields: the host sends them in their materialized form ---
    const fieldStore = new Map();
    const fieldSubs = new Map();
    const notifyField = (key) => {
      const subs = fieldSubs.get(key);
      if (!subs) return;
      for (const cb of Array.from(subs)) {
        try {
          cb();
        } catch {}
      }
    };
    const unwrapField = (value) => {
      if (!value || typeof value !== "object") return null;
      if (typeof value.__text === "string" && Array.isArray(value.ids)) {
        return {
          view: { text: value.__text, ids: value.ids },
          plain: value.__text,
        };
      }
      if (Array.isArray(value.__list)) {
        return {
          view: { items: value.__list },
          plain: value.__list.map((row) => (row ? row.value : null)),
        };
      }
      return null;
    };
    const writeState = (key, value) => {
      const field = unwrapField(value);
      if (!field) {
        if (fieldStore.delete(key)) notifyField(key);
        return writePlain(key, value);
      }
      fieldStore.set(key, field.view);
      notifyField(key);
      return writePlain(key, field.plain);
    };

    const NO_CARETS = [];
    const caretsByKey = new Map();
    const caretSubs = new Set();
    const applyCarets = (list) => {
      caretsByKey.clear();
      for (const caret of list) {
        if (!caret || typeof caret.key !== "string") continue;
        const bucket = caretsByKey.get(caret.key) || [];
        bucket.push(caret);
        caretsByKey.set(caret.key, bucket);
      }
      for (const cb of Array.from(caretSubs)) {
        try {
          cb();
        } catch {}
      }
    };

    const fields = {
      peekText: (key) => {
        const view = fieldStore.get(key);
        if (view && Array.isArray(view.ids)) return view;
        const plain = peek(key);
        return { text: typeof plain === "string" ? plain : "", ids: [] };
      },
      peekList: (key) => {
        const view = fieldStore.get(key);
        if (view && Array.isArray(view.items)) return view.items;
        const plain = peek(key);
        if (!Array.isArray(plain)) return [];
        return plain.map((value, index) => ({ id: "plain-" + index, value }));
      },
      subscribe: (key, cb) => {
        let subs = fieldSubs.get(key);
        if (!subs) {
          subs = new Set();
          fieldSubs.set(key, subs);
        }
        subs.add(cb);
        const stopPlain = state.subscribe(key, cb);
        return () => {
          subs.delete(cb);
          if (subs.size === 0) fieldSubs.delete(key);
          stopPlain();
        };
      },
      editText: (key, edit) => call("stateEditText", { key, ...edit }),
      editList: (key, edit) => call("stateEditList", { key, ...edit }),
      caretsFor: (key) => caretsByKey.get(key) || NO_CARETS,
      subscribeCarets: (cb) => {
        caretSubs.add(cb);
        return () => caretSubs.delete(cb);
      },
    };
    const replaceState = (state) => {
      const incoming = state && typeof state === "object" ? state : {};
      const keys = new Set([...stateStore.keys(), ...Object.keys(incoming)]);
      for (const key of keys) writeState(key, incoming[key]);
    };
    const state = {
      get: (key) => Promise.resolve(peek(key)),
      peek,
      set: (key, value) => {
        if (typeof key !== "string" || !key) {
          return Promise.reject(new Error("ph.state.set(key, value) requires a key"));
        }
        if (fieldStore.has(key)) {
          return Promise.reject(new Error(${JSON.stringify(SHARED_FIELD_READ_ONLY_STATE)}));
        }
        const next = value === undefined ? null : value;
        const json = jsonOf(next);
        if (json === null) {
          return Promise.reject(new Error("ph.state.set(key, value) needs a JSON value"));
        }
        if (new TextEncoder().encode(json).length > MAX_STATE_VALUE_BYTES) {
          return Promise.reject(
            new Error("ph.state.set(key, value) is limited to " + Math.floor(MAX_STATE_VALUE_BYTES / 1024) + " KB per value"),
          );
        }
        if (writeState(key, next)) post({ type: "state-changed", key, value: next });
        return Promise.resolve({ ok: true });
      },
      list: () => Promise.resolve(Array.from(stateStore, ([key, value]) => ({ key, value }))),
      subscribe: (key, cb) => {
        let subs = subscribers.get(key);
        if (!subs) {
          subs = new Set();
          subscribers.set(key, subs);
        }
        subs.add(cb);
        return () => {
          subs.delete(cb);
          if (subs.size === 0) subscribers.delete(key);
        };
      },
    };

    window.ph = {
      run: unavailable("run"),
      loadInsight: (shortId, opts) =>
        call("loadInsight", {
          shortId,
          dateRange: opts && opts.dateRange,
          variables: opts && opts.variables,
          refresh: opts && opts.refresh,
        }),
      query: (queryOrHogql, params, opts) =>
        call(
          "query",
          typeof queryOrHogql === "string"
            ? { hogql: queryOrHogql, params: params ?? {}, refresh: opts && opts.refresh }
            : { query: queryOrHogql, params: params ?? {}, refresh: opts && opts.refresh },
        ),
      capture: unavailable("capture"),
      state,
      fields,
      actions: { invoke: unavailable("actions.invoke") },
      agent: { request: unavailable("agent.request") },
      openExternal: (url) => post({ type: "open-external", url }),
      navigate: {
        toTask: unavailable("navigate.toTask"),
        toNewTask: unavailable("navigate.toNewTask"),
        toCanvas: unavailable("navigate.toCanvas"),
        toNewCanvas: unavailable("navigate.toNewCanvas"),
      },
    };

    // target="_blank" anchors open through the host; the sandbox blocks popups.
    const resolveExternalAnchorUrl = ${resolveExternalAnchorUrl.toString()};
    document.addEventListener(
      "click",
      (event) => {
        const url = resolveExternalAnchorUrl(event.target);
        if (!url) return;
        setTimeout(() => {
          if (!event.defaultPrevented) window.ph.openExternal(url);
        }, 0);
      },
      true,
    );

    const applyTheme = (theme) =>
      document.documentElement.classList.toggle("dark", theme === "dark");
    const applyViewport = (viewport) => {
      if (!viewport) return;
      world.style.transform =
        "translate(" + viewport.x + "px, " + viewport.y + "px) scale(" + viewport.zoom + ")";
    };

    // --- pointer and wheel relay: the host owns pan, zoom, and selection ---
    const fragmentElementOf = (target) =>
      target instanceof Element ? target.closest(".fragment") : null;
    let relayingPointer = false;
    const modifiersOf = (e) => ({
      shiftKey: e.shiftKey === true,
      metaKey: e.metaKey === true,
      ctrlKey: e.ctrlKey === true,
      altKey: e.altKey === true,
    });
    const pointerPayload = (phase, e) => ({
      type: "background-pointer",
      phase,
      clientX: e.clientX,
      clientY: e.clientY,
      button: e.button,
      ...modifiersOf(e),
    });
    document.addEventListener(
      "pointerdown",
      (e) => {
        const fragmentEl = fragmentElementOf(e.target);
        if (fragmentEl) {
          post({
            type: "fragment-pointer-down",
            id: fragmentEl.dataset.id || "",
            ...modifiersOf(e),
          });
          return;
        }
        e.preventDefault();
        relayingPointer = true;
        post(pointerPayload("down", e));
      },
      true,
    );
    window.addEventListener("pointermove", (e) => {
      if (relayingPointer) post(pointerPayload("move", e));
      post({ type: "pointer-move", clientX: e.clientX, clientY: e.clientY });
    });
    document.addEventListener("pointerleave", () => {
      post({ type: "pointer-leave" });
    });
    const endPointer = (e) => {
      if (!relayingPointer) return;
      relayingPointer = false;
      post(pointerPayload("up", e));
    };
    window.addEventListener("pointerup", endPointer);
    window.addEventListener("pointercancel", endPointer);

    // A fragment that can still scroll in the wheel direction keeps the
    // native scroll; everything else pans or zooms the board.
    const fragmentScrolls = (target, deltaX, deltaY) => {
      const fragmentEl = fragmentElementOf(target);
      if (!fragmentEl) return false;
      const vertical = Math.abs(deltaY) >= Math.abs(deltaX);
      for (let el = target; el && fragmentEl.contains(el); el = el.parentElement) {
        if (vertical) {
          if (el.scrollHeight <= el.clientHeight) continue;
          const atTop = el.scrollTop <= 0;
          const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
          if ((deltaY < 0 && !atTop) || (deltaY > 0 && !atBottom)) return true;
        } else {
          if (el.scrollWidth <= el.clientWidth) continue;
          const atStart = el.scrollLeft <= 0;
          const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1;
          if ((deltaX < 0 && !atStart) || (deltaX > 0 && !atEnd)) return true;
        }
      }
      return false;
    };
    window.addEventListener(
      "wheel",
      (e) => {
        const zooming = e.ctrlKey || e.metaKey;
        if (!zooming && fragmentScrolls(e.target, e.deltaX, e.deltaY)) return;
        e.preventDefault();
        post({
          type: "wheel",
          deltaX: e.deltaX,
          deltaY: e.deltaY,
          ctrlKey: e.ctrlKey,
          metaKey: e.metaKey,
          clientX: e.clientX,
          clientY: e.clientY,
        });
      },
      { passive: false },
    );

    // --- fragment runtime ---
    const decodeUnicodeEscapes = ${decodeJsxUnicodeEscapes.toString()};
    const jsxUnicodeEscapesPlugin = () => ({
      visitor: {
        JSXText(path) {
          const decoded = decodeUnicodeEscapes(path.node.value);
          if (decoded !== path.node.value) path.node.value = decoded;
        },
        JSXAttribute(path) {
          const v = path.node.value;
          if (v && v.type === "StringLiteral") {
            const decoded = decodeUnicodeEscapes(v.value);
            if (decoded !== v.value) {
              v.value = decoded;
              v.extra = undefined;
            }
          }
        },
      },
    });

    let runtimePromise = null;
    const loadRuntime = () => {
      if (runtimePromise) return runtimePromise;
      runtimePromise = Promise.all([import("react"), import("react-dom/client")])
        .then(([React, dom]) => {
          const ErrorBlock = ({ message }) =>
            React.createElement(
              "div",
              { className: "fragment-error" },
              React.createElement("div", { className: "fragment-error-title" }, "This fragment failed to render"),
              React.createElement("pre", null, message),
            );
          class Boundary extends React.Component {
            constructor(props) {
              super(props);
              this.state = { error: null };
            }
            static getDerivedStateFromError(error) {
              return { error };
            }
            componentDidCatch(error) {
              this.props.onError(error);
            }
            render() {
              if (this.state.error) {
                return React.createElement(ErrorBlock, { message: describeError(this.state.error) });
              }
              return this.props.children;
            }
          }
          return { React, createRoot: dom.createRoot, Boundary, ErrorBlock };
        })
        .catch((err) => {
          runtimePromise = null;
          throw err;
        });
      return runtimePromise;
    };

    const describeError = (err) => {
      const message = String((err && err.message) || err || "Unknown error");
      if (message.indexOf("Failed to fetch dynamically imported module") !== -1) {
        return "Could not load the fragment libraries from esm.sh. The board needs network access to https://esm.sh.";
      }
      return message;
    };
    const reportFragmentError = (id, err, message) =>
      post({
        type: "fragment-error",
        id,
        message: String(message ?? describeError(err)).slice(0, 10000),
        stack: err && err.stack ? String(err.stack).slice(0, 50000) : undefined,
      });

    const fragments = new Map();
    const applyGeometry = (el, f) => {
      el.style.left = f.x + "px";
      el.style.top = f.y + "px";
      el.style.width = f.w + "px";
      el.style.height = f.h + "px";
      el.style.zIndex = String(f.z ?? 0);
    };
    const renderErrorBlock = async (entry, seq, message) => {
      try {
        const { React, createRoot, ErrorBlock } = await loadRuntime();
        if (seq !== entry.mountSeq) return;
        if (!entry.root) entry.root = createRoot(entry.el);
        entry.root.render(React.createElement(ErrorBlock, { message }));
      } catch {
        if (seq !== entry.mountSeq || entry.root) return;
        entry.el.textContent = "";
        const block = document.createElement("div");
        block.className = "fragment-error";
        const title = document.createElement("div");
        title.className = "fragment-error-title";
        title.textContent = "This fragment failed to render";
        const pre = document.createElement("pre");
        pre.textContent = message;
        block.append(title, pre);
        entry.el.append(block);
      }
    };
    const mount = async (entry, fragment) => {
      const seq = ++entry.mountSeq;
      const id = fragment.id;
      try {
        const out = Babel.transform(fragment.code, {
          filename: id + ".tsx",
          plugins: [jsxUnicodeEscapesPlugin],
          presets: [
            ["react", { runtime: "automatic" }],
            ["typescript", { isTSX: true, allExtensions: true, onlyRemoveTypeImports: true }],
          ],
        }).code;
        const url = URL.createObjectURL(new Blob([out], { type: "text/javascript" }));
        let mod;
        try {
          mod = await import(url);
        } catch (err) {
          URL.revokeObjectURL(url);
          throw err;
        }
        if (seq !== entry.mountSeq) {
          URL.revokeObjectURL(url);
          return;
        }
        if (entry.moduleUrl) URL.revokeObjectURL(entry.moduleUrl);
        entry.moduleUrl = url;
        const Comp = mod.default;
        if (typeof Comp !== "function") {
          throw new Error("A fragment must export default a React component.");
        }
        const { React, createRoot, Boundary } = await loadRuntime();
        if (seq !== entry.mountSeq) return;
        if (!entry.root) entry.root = createRoot(entry.el);
        entry.errored = false;
        entry.root.render(
          React.createElement(
            Boundary,
            {
              key: fragment.codeVersion,
              onError: (error) => {
                entry.errored = true;
                reportFragmentError(id, error);
              },
            },
            React.createElement(Comp),
          ),
        );
        requestAnimationFrame(() => {
          if (seq !== entry.mountSeq || entry.errored) return;
          post({ type: "fragment-rendered", id });
        });
      } catch (err) {
        if (seq !== entry.mountSeq) return;
        const message = describeError(err);
        reportFragmentError(id, err, message);
        await renderErrorBlock(entry, seq, message);
      }
    };
    const upsert = (fragment) => {
      if (!fragment || typeof fragment.id !== "string") return;
      let entry = fragments.get(fragment.id);
      if (!entry) {
        const el = document.createElement("div");
        el.className = "fragment";
        el.dataset.id = fragment.id;
        world.appendChild(el);
        entry = { el, root: null, codeVersion: null, moduleUrl: null, mountSeq: 0, errored: false };
        fragments.set(fragment.id, entry);
      }
      applyGeometry(entry.el, fragment);
      if (entry.codeVersion === fragment.codeVersion) return;
      entry.codeVersion = fragment.codeVersion;
      void mount(entry, fragment);
    };
    const remove = (id) => {
      const entry = fragments.get(id);
      if (!entry) return;
      fragments.delete(id);
      entry.mountSeq += 1;
      if (entry.root) entry.root.unmount();
      if (entry.moduleUrl) URL.revokeObjectURL(entry.moduleUrl);
      entry.el.remove();
    };
    const syncFragments = (list) => {
      const keep = new Set();
      for (const fragment of list) {
        if (fragment && typeof fragment.id === "string") keep.add(fragment.id);
      }
      for (const id of Array.from(fragments.keys())) {
        if (!keep.has(id)) remove(id);
      }
      for (const fragment of list) upsert(fragment);
    };
    const setSelection = (ids) => {
      const selected = new Set(Array.isArray(ids) ? ids : []);
      for (const [fragmentId, entry] of fragments) {
        entry.el.classList.toggle("selected", selected.has(fragmentId));
      }
    };

    window.addEventListener("message", (e) => {
      if (e.source !== window.parent) return;
      const d = e.data;
      if (!d || d.channel !== CHANNEL) return;
      switch (d.type) {
        case "init":
          applyTheme(d.theme);
          applyViewport(d.viewport);
          replaceState(d.state);
          syncFragments(Array.isArray(d.fragments) ? d.fragments : []);
          break;
        case "set-viewport":
          applyViewport(d.viewport);
          break;
        case "upsert-fragment":
          upsert(d.fragment);
          break;
        case "remove-fragment":
          remove(d.id);
          break;
        case "set-state":
          writeState(d.key, d.value);
          break;
        case "set-theme":
          applyTheme(d.theme);
          break;
        case "set-selection":
          setSelection(d.ids);
          break;
        case "set-carets":
          applyCarets(Array.isArray(d.carets) ? d.carets : []);
          break;
        case "data-response": {
          const p = pending.get(d.id);
          if (!p) return;
          pending.delete(d.id);
          d.ok ? p.resolve(d.result) : p.reject(new Error(d.error || "data error"));
          break;
        }
      }
    });

    post({ type: "ready" });
  `;

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<script>
  var canvasImportMap = ${importMap};
  canvasImportMap.imports[${JSON.stringify(CANVAS_SDK_SPECIFIER)}] =
    URL.createObjectURL(new Blob([${JSON.stringify(BOARD_FRAME_SDK_MODULE_SOURCE)}], { type: "text/javascript" }));
  var canvasImportMapTag = document.createElement("script");
  canvasImportMapTag.type = "importmap";
  canvasImportMapTag.textContent = JSON.stringify(canvasImportMap);
  document.head.appendChild(canvasImportMapTag);
</script>
${TAILWIND_V4}
${FREEFORM_QUILL_CSS_URLS.map(
  (href) => `<link rel="stylesheet" href="${href}" />`,
).join("\n")}
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }
  html.dark { color-scheme: dark; }
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; color: var(--foreground, inherit); background: var(--background, transparent); touch-action: none; }
  #world { position: absolute; left: 0; top: 0; transform-origin: 0 0; will-change: transform; }
  .fragment { position: absolute; overflow: auto; background: var(--card, var(--background, #fff)); color: var(--card-foreground, inherit); border: 1px solid var(--border, rgba(128, 128, 128, 0.35)); border-radius: 8px; }
  .fragment.selected { border-color: var(--ring, var(--primary, #1d4ed8)); }
  .fragment-error { padding: 12px; font-size: 12px; color: var(--destructive, #b91c1c); }
  .ph-caret-name { animation: ph-caret-fade 300ms 2500ms forwards; }
  @keyframes ph-caret-fade { to { opacity: 0; } }
  .fragment-error-title { margin-bottom: 4px; font-weight: 600; }
  .fragment-error pre { margin: 0; font-size: 11px; white-space: pre-wrap; word-break: break-word; opacity: 0.85; }
</style>
</head>
<body>
<div id="world"></div>
<script type="module">${bootstrap}</script>
</body>
</html>`;
}

// Same policy as the freeform sandbox minus the analytics hosts: fragment data
// goes over postMessage, so connect-src only needs the module CDNs.
function contentSecurityPolicy(): string {
  const esm = FREEFORM_ESM_HOST;
  return [
    "default-src 'none'",
    `script-src 'unsafe-inline' 'unsafe-eval' blob: ${TAILWIND_CDN} ${esm}`,
    `style-src 'unsafe-inline' ${esm}`,
    `font-src data: ${esm}`,
    "img-src data: blob: https:",
    "worker-src blob:",
    `connect-src ${esm} ${TAILWIND_CDN}`,
  ].join("; ");
}
