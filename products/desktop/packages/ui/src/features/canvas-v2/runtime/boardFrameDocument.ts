import {
  buildImportMap,
  FREEFORM_BABEL_URL,
  FREEFORM_ESM_HOST,
  FREEFORM_QUILL_CSS_URLS,
} from "@posthog/core/canvas/freeformWhitelist";
import {
  CANVAS_SDK_SPECIFIER,
  CANVAS_V2_ALLOWED_IMPORTS,
  CANVAS_V2_CHANNEL,
  CANVAS_V2_FIELD_MAX_ENTRIES,
  CANVAS_V2_MAX_STATE_VALUE_BYTES,
  CANVAS_V2_MODULE_SCHEME,
  CANVAS_V2_TAILWIND_PREFIX,
  vendoredModuleUrl,
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

const TAILWIND_URL = `${CANVAS_V2_TAILWIND_PREFIX}browser@4.3.1`;

const TAILWIND_STYLE = `<style type="text/tailwindcss">
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
        "h-full w-full resize-none rounded-(--radius-sm) border border-border bg-transparent p-2 text-sm leading-relaxed outline-none " +
        (className || ""),
    }),
    createElement(
      "div",
      {
        ref: mirrorRef,
        "aria-hidden": "true",
        className:
          "pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words p-2 text-sm leading-relaxed opacity-0 " +
          (className || ""),
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

const RANGE_UNITS = { h: "HOUR", d: "DAY", w: "WEEK", m: "MONTH" };
const RANGE_NAMES = { h: "hours", d: "days", w: "weeks", m: "months" };
const DEFAULT_DATE_RANGE = { date_from: "-7d", date_to: null };
const RANGE_PATTERN = /^-(\\d+)([hdwm])$/;

// The settings of one fragment, kept in board state under the fragment id. A
// person changes what a fragment shows without opening its code, and every
// collaborator sees the same settings.
export function useFragmentSettings(fragmentId, defaults) {
  const key = "settings:" + String(fragmentId || "fragment");
  const [stored, setStored] = useSharedState(key, null);
  const settings = Object.assign(
    {},
    defaults,
    stored && typeof stored === "object" ? stored : null,
  );
  const update = useCallback(
    (patch) =>
      setStored((current) =>
        Object.assign(
          {},
          defaults,
          current && typeof current === "object" ? current : null,
          patch,
        ),
      ),
    [setStored],
  );
  return [settings, update];
}

const BOARD_DATE_RANGE_KEY = "dateRange";
const scopedRangeKey = (id) => "dateRange:" + String(id);

// The HogQL time bounds and the words that go with one range.
export function describeRange(range) {
  const from = range && range.date_from ? String(range.date_from) : "-7d";
  const match = RANGE_PATTERN.exec(from);
  const amount = match ? Number(match[1]) : 7;
  const unit = match ? match[2] : "d";
  const clickhouseUnit = RANGE_UNITS[unit] || "DAY";
  return {
    since: "now() - INTERVAL " + amount + " " + clickhouseUnit,
    previousSince: "now() - INTERVAL " + amount * 2 + " " + clickhouseUnit,
    label: "Last " + amount + " " + (RANGE_NAMES[unit] || "days"),
  };
}

// The date range a data fragment follows. Pass the fragment id and the
// fragment obeys the nearest date frame that holds it. With no id, and with no
// date frame around it, it follows the range of the whole board.
export function useDateRange(fragmentId) {
  const all = useBoardFragments();
  const keys = useMemo(() => {
    const list = fragmentId
      ? holdersOf(fragmentId, all).map((holder) => scopedRangeKey(holder.id))
      : [];
    list.push(BOARD_DATE_RANGE_KEY);
    return list;
  }, [all, fragmentId]);
  const signature = keys.join("|");
  const keysRef = useRef(keys);
  keysRef.current = keys;

  const [found, setFound] = useState({
    key: BOARD_DATE_RANGE_KEY,
    range: DEFAULT_DATE_RANGE,
  });

  useEffect(() => {
    const read = () => {
      for (const candidate of keysRef.current) {
        const value = globalThis.ph.state.peek(candidate);
        if (value && typeof value === "object") {
          setFound({ key: candidate, range: value });
          return;
        }
      }
      setFound({ key: BOARD_DATE_RANGE_KEY, range: DEFAULT_DATE_RANGE });
    };
    read();
    const offs = keysRef.current.map((candidate) =>
      globalThis.ph.state.subscribe(candidate, read),
    );
    return () => {
      for (const off of offs) off();
    };
  }, [signature]);

  const setRange = useCallback(
    (next) =>
      globalThis.ph.state.set(
        found.key,
        typeof next === "function" ? next(found.range) : next,
      ),
    [found.key, found.range],
  );

  const parts = describeRange(found.range);
  return {
    range: found.range || DEFAULT_DATE_RANGE,
    setRange,
    scoped: found.key !== BOARD_DATE_RANGE_KEY,
    since: parts.since,
    previousSince: parts.previousSince,
    label: parts.label,
  };
}

// A date frame owns the range that everything inside it follows.
export function useOwnedDateRange(fragmentId) {
  const [range, setRange] = useSharedState(
    scopedRangeKey(fragmentId),
    DEFAULT_DATE_RANGE,
  );
  const parts = describeRange(range);
  return {
    range: range || DEFAULT_DATE_RANGE,
    setRange,
    since: parts.since,
    previousSince: parts.previousSince,
    label: parts.label,
  };
}

// A value that is safe inside a HogQL string literal.
export function hogqlString(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return "'" + text.split("\\\\").join("\\\\\\\\").split("'").join("\\\\'") + "'";
}

// Runs a HogQL query and keeps loading, error, and rows apart. Pass null as the
// query to hold the fragment at rest.
export function useHogQL(sql) {
  const [state, setState] = useState({
    loading: Boolean(sql),
    error: null,
    columns: [],
    rows: [],
  });
  const [nonce, setNonce] = useState(0);
  const retry = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!sql) {
      setState({ loading: false, error: null, columns: [], rows: [] });
      return;
    }
    let cancelled = false;
    setState({ loading: true, error: null, columns: [], rows: [] });
    globalThis.ph
      .query(sql)
      .then((result) => {
        if (cancelled) return;
        setState({
          loading: false,
          error: null,
          columns: (result && result.columns) || [],
          rows: (result && result.results) || [],
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setState({
          loading: false,
          error: messageOf(error),
          columns: [],
          rows: [],
        });
      });
    return () => {
      cancelled = true;
    };
  }, [sql, nonce]);

  return {
    loading: state.loading,
    error: state.error,
    columns: state.columns,
    rows: state.rows,
    retry,
  };
}

// The event names this project sends, most used first, for a picker.
export function useEventNames() {
  const result = useHogQL(
    "SELECT event, count() AS uses FROM events WHERE timestamp >= now() - INTERVAL 30 DAY GROUP BY event ORDER BY uses DESC LIMIT 100",
  );
  const names = useMemo(
    () =>
      result.rows
        .map((row) => (row && row[0] ? String(row[0]) : ""))
        .filter(Boolean),
    [result.rows],
  );
  return { names, loading: result.loading, error: result.error };
}

// 12345 reads as 12.3k where an axis or a tile has little room.
export function formatCompact(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1000000) {
    return (number / 1000000).toFixed(1).replace(/\\.0$/, "") + "M";
  }
  if (Math.abs(number) >= 1000) {
    return (number / 1000).toFixed(1).replace(/\\.0$/, "") + "k";
  }
  return String(number);
}

// --- containers: a fragment that holds the fragments dropped on top of it ---

const areaOf = (box) => Math.max(1, box.w * box.h);
const holds = (box, item) => {
  const cx = item.x + item.w / 2;
  const cy = item.y + item.h / 2;
  return cx > box.x && cx < box.x + box.w && cy > box.y && cy < box.y + box.h;
};

// The fragments that hold this one, the smallest first. A fragment is inside
// another when its center is, so a fragment dragged half way in still counts.
export function holdersOf(fragmentId, all) {
  const self = all.find((item) => item.id === fragmentId);
  if (!self) return [];
  return all
    .filter(
      (other) =>
        other.id !== fragmentId &&
        areaOf(other) > areaOf(self) &&
        holds(other, self),
    )
    .sort((a, b) => areaOf(a) - areaOf(b));
}

// Every fragment on the board with its box, kept in step with the host.
export function useBoardFragments() {
  const [list, setList] = useState(() => globalThis.ph.board.list());
  useEffect(() => {
    const read = () => setList(globalThis.ph.board.list());
    read();
    return globalThis.ph.board.subscribe(read);
  }, []);
  return list;
}

// The fragments this person has selected on the board.
export function useBoardSelection() {
  const [ids, setIds] = useState(() => globalThis.ph.board.selection());
  useEffect(() => {
    setIds(globalThis.ph.board.selection());
    return globalThis.ph.board.subscribeSelection(setIds);
  }, []);
  return ids;
}

// The fragment the board shows full page, or null.
export function useBoardFocus() {
  const [id, setId] = useState(() => globalThis.ph.board.focused());
  useEffect(() => {
    setId(globalThis.ph.board.focused());
    return globalThis.ph.board.subscribeFocus(setId);
  }, []);
  return id;
}

// True while somebody drags or resizes on the board. A container waits for the
// gesture to end, so it never pulls a fragment out of the pointer.
export function useBoardBusy() {
  const [busy, setBusy] = useState(() => globalThis.ph.board.isBusy());
  useEffect(() => {
    setBusy(globalThis.ph.board.isBusy());
    return globalThis.ph.board.subscribeBusy(setBusy);
  }, []);
  return busy;
}

// Puts the items in a grid inside a box, left to right and top to bottom.
export function gridRects(items, box, options) {
  const opts = options || {};
  const gap = typeof opts.gap === "number" ? opts.gap : 12;
  const columns = Math.max(1, Math.min(8, Math.round(opts.columns || 2)));
  if (items.length === 0) return [];
  const rows = Math.ceil(items.length / columns);
  const cellWidth = (box.w - gap * (columns - 1)) / columns;
  const cellHeight = (box.h - gap * (rows - 1)) / rows;
  return items.map((item, index) => ({
    id: item.id,
    x: box.x + (index % columns) * (cellWidth + gap),
    y: box.y + Math.floor(index / columns) * (cellHeight + gap),
    w: Math.max(80, cellWidth),
    h: Math.max(60, cellHeight),
  }));
}

/**
 * Makes a fragment a container: it knows the fragments that sit on it and can
 * place them.
 *
 * padding  the space kept clear at the edge of the container
 * header   the space kept clear at the top, for a title bar
 * layout   given the children and the free box, gives back the boxes to use
 * follow   with no layout, the children move when the container moves
 */
export function useContainer(fragmentId, options) {
  const opts = options || {};
  const padding = typeof opts.padding === "number" ? opts.padding : 16;
  const header = typeof opts.header === "number" ? opts.header : 0;
  const layout = typeof opts.layout === "function" ? opts.layout : null;
  const follow = opts.follow === true;

  const all = useBoardFragments();
  const busy = useBoardBusy();
  const self = useMemo(
    () => all.find((item) => item.id === fragmentId) || null,
    [all, fragmentId],
  );

  const children = useMemo(() => {
    if (!self) return [];
    const inside = all.filter(
      (item) => item.id !== fragmentId && holds(self, item),
    );
    // The smallest fragment that holds a child owns it, so a container inside
    // a container keeps its own contents.
    const mine = inside.filter((child) =>
      inside.every(
        (other) =>
          other.id === child.id ||
          areaOf(other) <= areaOf(child) ||
          !holds(other, child),
      ),
    );
    return mine.sort((a, b) => a.y - b.y || a.x - b.x);
  }, [all, fragmentId, self]);

  const inner = useMemo(() => {
    if (!self) return { x: 0, y: 0, w: 0, h: 0 };
    return {
      x: self.x + padding,
      y: self.y + padding + header,
      w: Math.max(1, self.w - padding * 2),
      h: Math.max(1, self.h - padding * 2 - header),
    };
  }, [self, padding, header]);

  const lastBox = useRef(null);
  useEffect(() => {
    if (!self || busy) return;
    const previous = lastBox.current;
    lastBox.current = { x: self.x, y: self.y, w: self.w, h: self.h };
    if (children.length === 0) return;

    let wanted = null;
    if (layout) {
      wanted = layout(children, inner);
    } else if (follow && previous) {
      const dx = self.x - previous.x;
      const dy = self.y - previous.y;
      if (dx === 0 && dy === 0) return;
      wanted = children.map((child) => ({
        id: child.id,
        x: child.x + dx,
        y: child.y + dy,
      }));
    }
    if (!Array.isArray(wanted) || wanted.length === 0) return;

    // Only the boxes that really change are sent, or the board and the
    // container would write to each other without end.
    const known = new Map(children.map((child) => [child.id, child]));
    const moves = [];
    for (const want of wanted) {
      const child = want ? known.get(want.id) : null;
      if (!child) continue;
      const next = {
        id: child.id,
        x: Math.round(typeof want.x === "number" ? want.x : child.x),
        y: Math.round(typeof want.y === "number" ? want.y : child.y),
        w: Math.round(typeof want.w === "number" ? want.w : child.w),
        h: Math.round(typeof want.h === "number" ? want.h : child.h),
        hidden: want.hidden === true,
      };
      if (
        next.x === child.x &&
        next.y === child.y &&
        next.w === child.w &&
        next.h === child.h &&
        next.hidden === (child.hidden === true)
      ) {
        continue;
      }
      moves.push(next);
    }
    if (moves.length === 0) return;
    globalThis.ph.board.arrange(moves).catch(() => {});
  }, [self, children, inner, busy, layout, follow]);

  return { self, children, inner, busy };
}

`;

export interface BoardFrameOptions {
  vendoredModules: boolean;
}

export function boardFramePolicy(vendoredModules: boolean): string {
  return contentSecurityPolicy(vendoredModules);
}

export function buildBoardFrameDocument(options: BoardFrameOptions): string {
  const moduleUrl = (url: string): string =>
    options.vendoredModules ? vendoredModuleUrl(url) : url;
  const map = buildImportMap();
  const importMap = JSON.stringify({
    imports: Object.fromEntries(
      Object.entries(map.imports).map(([name, url]) => [name, moduleUrl(url)]),
    ),
  });
  const csp = contentSecurityPolicy(options.vendoredModules);

  const bootstrap = /* js */ `
    import * as Babel from "${moduleUrl(FREEFORM_BABEL_URL)}";
    try {
      delete Navigator.prototype.sendBeacon;
    } catch (error) {
      Navigator.prototype.sendBeacon = undefined;
    }

    document.addEventListener("securitypolicyviolation", (event) => {
      post({
        type: "policy-violation",
        directive: String(event.effectiveDirective || "").slice(0, 64),
        blocked: String(event.blockedURI || "").slice(0, 512),
      });
    });

    const linkGuard = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeName === "LINK") node.remove();
        }
      }
    });
    linkGuard.observe(document.documentElement, { childList: true, subtree: true });

    for (const name of [
      "RTCPeerConnection",
      "webkitRTCPeerConnection",
      "mozRTCPeerConnection",
      "RTCDataChannel",
      "RTCSessionDescription",
      "RTCIceCandidate",
    ]) {
      try {
        delete globalThis[name];
      } catch (error) {
        globalThis[name] = undefined;
      }
    }

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

    // --- board geometry: what a container fragment sees around itself ---
    let boardBusy = false;
    let selectedIds = [];
    const boardSubs = new Set();
    const selectionSubs = new Set();
    const focusSubs = new Set();
    const notifyFocus = () => {
      for (const cb of Array.from(focusSubs)) {
        try {
          cb(focusedId);
        } catch {}
      }
    };
    const busySubs = new Set();
    let boardNotifyQueued = false;
    const notifyBoard = () => {
      if (boardNotifyQueued) return;
      boardNotifyQueued = true;
      queueMicrotask(() => {
        boardNotifyQueued = false;
        for (const cb of Array.from(boardSubs)) {
          try {
            cb();
          } catch {}
        }
      });
    };
    const setBusy = (next) => {
      const value = next === true;
      if (value === boardBusy) return;
      boardBusy = value;
      for (const cb of Array.from(busySubs)) {
        try {
          cb(value);
        } catch {}
      }
    };
    // A copy, so fragment code cannot write the frame's own record.
    const boardRects = () => {
      const list = [];
      for (const [fragmentId, entry] of fragments) {
        const f = entry.fragment;
        if (!f) continue;
        list.push({
          id: fragmentId,
          title: typeof f.title === "string" ? f.title : "",
          x: f.x,
          y: f.y,
          w: f.w,
          h: f.h,
          z: f.z ?? 0,
          surface: f.surface === "plain" ? "plain" : "card",
          hidden: f.hidden === true,
        });
      }
      return list;
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
      board: {
        list: boardRects,
        subscribe: (cb) => {
          boardSubs.add(cb);
          return () => boardSubs.delete(cb);
        },
        isBusy: () => boardBusy,
        subscribeBusy: (cb) => {
          busySubs.add(cb);
          return () => busySubs.delete(cb);
        },
        focused: () => focusedId,
        subscribeFocus: (cb) => {
          focusSubs.add(cb);
          return () => focusSubs.delete(cb);
        },
        selection: () => selectedIds.slice(),
        subscribeSelection: (cb) => {
          selectionSubs.add(cb);
          return () => selectionSubs.delete(cb);
        },
        arrange: (items) => call("arrangeFragments", { items }),
      },
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

    // A popup is placed once, in page pixels, so it cannot follow the board.
    // When the board or a fragment moves, the popup is shut.
    const closeFloating = () => {
      let floating = false;
      for (const node of document.body.children) {
        if (node !== world && node.childElementCount > 0) floating = true;
      }
      if (!floating) return;
      const target =
        document.activeElement instanceof Element
          ? document.activeElement
          : document.body;
      target.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Escape",
          code: "Escape",
          bubbles: true,
          cancelable: true,
        }),
      );
    };

    const applyTheme = (theme) =>
      document.documentElement.classList.toggle("dark", theme === "dark");
    const GRID_STEP = 24;
    let lastViewport = null;
    const applyViewport = (viewport) => {
      if (!viewport) return;
      if (framedBox !== null) {
        lastViewport = viewport;
        return;
      }
      if (
        !lastViewport ||
        lastViewport.x !== viewport.x ||
        lastViewport.y !== viewport.y ||
        lastViewport.zoom !== viewport.zoom
      ) {
        closeFloating();
      }
      lastViewport = viewport;
      world.style.transform =
        "translate(" + viewport.x + "px, " + viewport.y + "px) scale(" + viewport.zoom + ")";
      const step = GRID_STEP * viewport.zoom;
      const style = document.body.style;
      if (focusedId !== null) {
        style.backgroundImage = "none";
        return;
      }
      if (step < 9) {
        style.backgroundImage = "none";
        return;
      }
      style.backgroundImage = "radial-gradient(var(--ph-grid-dot) 1px, transparent 1px)";
      style.backgroundSize = step + "px " + step + "px";
      style.backgroundPosition = viewport.x + "px " + viewport.y + "px";
    };

    // --- pointer and wheel relay: the host owns pan, zoom, and selection ---
    const fragmentElementOf = (target) =>
      target instanceof Element ? target.closest(".fragment") : null;
    // A menu or a popup that a fragment opens is put in the body, outside the
    // world. It belongs to the fragment, so the board must not take its
    // pointer stream, or the person cannot pick anything in it.
    const onBoardSurface = (target) =>
      !(target instanceof Element) ||
      target === document.body ||
      target === document.documentElement ||
      world.contains(target);
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
        if (!onBoardSurface(e.target)) return;
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
        if (!onBoardSurface(e.target)) return;
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

    const ALLOWED_IMPORTS = new Set(${JSON.stringify([...CANVAS_V2_ALLOWED_IMPORTS])});
    const guardSource = (path) => {
      const source = path.node.source;
      if (!source) return;
      if (ALLOWED_IMPORTS.has(source.value)) return;
      throw path.buildCodeFrameError(
        '"' + source.value + '" is not a module a fragment can import.',
      );
    };
    const importGuardPlugin = () => ({
      visitor: {
        ImportDeclaration: guardSource,
        ExportNamedDeclaration: guardSource,
        ExportAllDeclaration: guardSource,
        Import(path) {
          throw path.buildCodeFrameError(
            "import() is not allowed in a fragment. Import the module at the top of the file.",
          );
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
              React.createElement("div", { className: "fragment-error-title" }, "This fragment did not run"),
              React.createElement("pre", null, message),
              React.createElement("div", { className: "fragment-error-hint" }, "Select Edit code in the fragment menu to fix it."),
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
        return "The fragment libraries did not load. Reopen the board, and tell us if it happens again.";
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
      el.style.zIndex = String(f.z ?? 0);
      el.style.display = f.hidden === true ? "none" : "";
      if (framedBox !== null && f.id === focusedId) {
        el.style.left = "0px";
        el.style.top = "0px";
        el.style.width = "100%";
        el.style.height = "100%";
        return;
      }
      if (framedBox !== null && boxHolds(framedBox, f)) {
        el.style.left =
          ((f.x - framedBox.x) / framedBox.w) * 100 + "%";
        el.style.top = ((f.y - framedBox.y) / framedBox.h) * 100 + "%";
        el.style.width = (f.w / framedBox.w) * 100 + "%";
        el.style.height = (f.h / framedBox.h) * 100 + "%";
        return;
      }
      el.style.left = f.x + "px";
      el.style.top = f.y + "px";
      el.style.width = f.w + "px";
      el.style.height = f.h + "px";
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
        title.textContent = "This fragment did not run";
        const pre = document.createElement("pre");
        pre.textContent = message;
        const hint = document.createElement("div");
        hint.className = "fragment-error-hint";
        hint.textContent = "Select Edit code in the fragment menu to fix it.";
        block.append(title, pre, hint);
        entry.el.append(block);
      }
    };
    const mount = async (entry, fragment) => {
      const seq = ++entry.mountSeq;
      const id = fragment.id;
      try {
        const out = Babel.transform(fragment.code, {
          filename: id + ".tsx",
          plugins: [importGuardPlugin, jsxUnicodeEscapesPlugin],
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
            React.createElement(Comp, { fragmentId: id }),
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
        if (fragment.surface === "plain") el.classList.add("fragment-plain");
        el.dataset.id = fragment.id;
        world.appendChild(el);
        entry = { el, root: null, codeVersion: null, code: null, moduleUrl: null, mountSeq: 0, errored: false, fragment: null };
        fragments.set(fragment.id, entry);
      }
      const before = entry.fragment;
      if (
        before &&
        (before.x !== fragment.x ||
          before.y !== fragment.y ||
          before.w !== fragment.w ||
          before.h !== fragment.h)
      ) {
        closeFloating();
      }
      entry.fragment = {
        id: fragment.id,
        title: fragment.title,
        x: fragment.x,
        y: fragment.y,
        w: fragment.w,
        h: fragment.h,
        z: fragment.z,
        surface: fragment.surface,
        hidden: fragment.hidden === true,
      };
      notifyBoard();
      applyGeometry(entry.el, fragment);
      if (before && before.hidden === true && fragment.hidden !== true) {
        entry.el.classList.remove("entering");
        void entry.el.offsetWidth;
        entry.el.classList.add("entering");
      }
      entry.el.classList.toggle("fragment-plain", fragment.surface === "plain");
      entry.el.classList.toggle("focused", fragment.id === focusedId);
      if (focusedId !== null) applyFocus();
      if (entry.codeVersion === fragment.codeVersion && entry.code === fragment.code) return;
      entry.codeVersion = fragment.codeVersion;
      entry.code = fragment.code;
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
      notifyBoard();
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
    let focusedId = null;
    let framedBox = null;
    const boxHolds = (box, item) => {
      const cx = item.x + item.w / 2;
      const cy = item.y + item.h / 2;
      return cx > box.x && cx < box.x + box.w && cy > box.y && cy < box.y + box.h;
    };
    // A frame goes full page with the fragments it holds, so a slideshow can
    // be presented. Everything else is left out of the picture.
    const applyFocus = () => {
      const target = focusedId === null ? null : fragments.get(focusedId);
      const box = target && target.fragment ? target.fragment : null;
      let held = 0;
      for (const [fragmentId, entry] of fragments) {
        const inside =
          box !== null &&
          fragmentId !== focusedId &&
          entry.fragment !== null &&
          boxHolds(box, entry.fragment);
        if (inside) held += 1;
        entry.el.classList.toggle("focused", fragmentId === focusedId);
        entry.el.classList.toggle("in-frame", inside);
      }
      framedBox = held > 0 ? box : null;
      document.body.classList.toggle(
        "ph-focus",
        focusedId !== null && framedBox === null,
      );
      document.body.classList.toggle("ph-focus-frame", framedBox !== null);
      for (const entry of fragments.values()) {
        if (entry.fragment) applyGeometry(entry.el, entry.fragment);
      }
      if (focusedId !== null) document.body.style.backgroundImage = "none";
      else applyViewport(lastViewport);
    };
    const setFocus = (id) => {
      focusedId = typeof id === "string" ? id : null;
      applyFocus();
      notifyFocus();
    };

    const setSelection = (ids) => {
      selectedIds = Array.isArray(ids) ? ids.slice() : [];
      const selected = new Set(selectedIds);
      for (const [fragmentId, entry] of fragments) {
        entry.el.classList.toggle("selected", selected.has(fragmentId));
      }
      for (const cb of Array.from(selectionSubs)) {
        try {
          cb(selectedIds);
        } catch {}
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
        case "set-focus":
          setFocus(d.id);
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
        case "set-busy":
          setBusy(d.busy);
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
<meta http-equiv="x-dns-prefetch-control" content="off" />
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
<script type="module" src="${moduleUrl(TAILWIND_URL)}"></script>
${TAILWIND_STYLE}
${FREEFORM_QUILL_CSS_URLS.map(
  (href) => `<link rel="stylesheet" href="${moduleUrl(href)}" />`,
).join("\n")}
<style>
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }
  html.dark { color-scheme: dark; }
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; color: var(--foreground, inherit); background-color: var(--background, transparent); background-image: radial-gradient(var(--ph-grid-dot) 1px, transparent 1px); background-repeat: repeat; touch-action: none; }
  :root { --ph-plain-hover: rgba(17, 17, 17, 0.035); --ph-grid-dot: rgba(17, 17, 17, 0.10); --ph-card-shadow: 0 1px 2px rgba(16, 18, 22, 0.05), 0 4px 12px -2px rgba(16, 18, 22, 0.08); --ph-card-shadow-hover: 0 1px 2px rgba(16, 18, 22, 0.06), 0 10px 24px -6px rgba(16, 18, 22, 0.14); }
  html.dark { --ph-plain-hover: rgba(255, 255, 255, 0.05); --ph-grid-dot: rgba(255, 255, 255, 0.09); --ph-card-shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 4px 12px -2px rgba(0, 0, 0, 0.45); --ph-card-shadow-hover: 0 1px 2px rgba(0, 0, 0, 0.45), 0 10px 24px -6px rgba(0, 0, 0, 0.6); }
  #world { position: absolute; left: 0; top: 0; transform-origin: 0 0; will-change: transform; }
  .fragment { position: absolute; overflow: auto; background: var(--card, var(--background, #fff)); color: var(--card-foreground, inherit); border: 1px solid var(--border, rgba(128, 128, 128, 0.35)); border-radius: 10px; box-shadow: var(--ph-card-shadow); transition: box-shadow 160ms ease, filter 160ms ease; }
  .fragment:hover { box-shadow: var(--ph-card-shadow-hover); }
  .fragment-plain, .fragment-plain.selected { background: transparent; border-color: transparent; box-shadow: none; }
  .fragment-plain:hover { background: var(--ph-plain-hover); border-color: transparent; box-shadow: none; }
  body.ph-focus { background-image: none; }
  body.ph-focus #world { transform: none !important; will-change: auto !important; }
  body.ph-focus .fragment { display: none; }
  body.ph-focus-frame { background-image: none; }
  body.ph-focus-frame #world { transform: none !important; will-change: auto !important; }
  body.ph-focus-frame .fragment { display: none; }
  body.ph-focus-frame .fragment.focused,
  body.ph-focus-frame .fragment.in-frame { display: block; position: fixed !important; }
  body.ph-focus-frame .fragment.focused { border: 0; border-radius: 0; background: transparent; box-shadow: none; overflow: hidden; }
  @keyframes ph-slide-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .fragment.entering { animation: ph-slide-in 220ms cubic-bezier(0.32, 0.72, 0, 1); }
  @media (prefers-reduced-motion: reduce) { .fragment.entering { animation: none; } }
  body.ph-focus .fragment.focused { display: block; position: fixed !important; left: 0 !important; top: 0 !important; right: 0 !important; bottom: 0 !important; width: auto !important; height: auto !important; border: 0; border-radius: 0; background: var(--card, var(--background, #fff)); box-shadow: none; overflow: auto; }
  .fragment.selected { box-shadow: var(--ph-card-shadow-hover); }
  .fragment-error { display: flex; height: 100%; flex-direction: column; gap: 8px; overflow: auto; padding: 16px; font-size: 12px; }
  .ph-caret-name { animation: ph-caret-fade 300ms 2500ms forwards; }
  @keyframes ph-caret-fade { to { opacity: 0; } }
  .fragment-error-title { font-weight: 600; color: var(--destructive, #b91c1c); }
  .fragment-error-hint { color: var(--muted-foreground, #6b7280); font-size: 11px; }
  .fragment-error pre { margin: 0; max-height: 60%; overflow: auto; border-radius: 6px; background: var(--muted, rgba(128, 128, 128, 0.12)); padding: 8px; color: var(--muted-foreground, #6b7280); font-size: 11px; white-space: pre-wrap; word-break: break-word; }
</style>
</head>
<body>
<div id="world"></div>
<script type="module">${bootstrap}</script>
</body>
</html>`;
}

function contentSecurityPolicy(vendoredModules: boolean): string {
  const modules = vendoredModules
    ? `${CANVAS_V2_MODULE_SCHEME}:`
    : `${CANVAS_V2_TAILWIND_PREFIX} ${FREEFORM_ESM_HOST}`;
  return [
    "default-src 'none'",
    `script-src 'unsafe-inline' blob: ${modules}`,
    `style-src 'unsafe-inline' ${modules}`,
    `font-src data: ${modules}`,
    "img-src data: blob:",
    "media-src data: blob:",
    "worker-src blob:",
    "connect-src 'none'",
    "prefetch-src 'none'",
    "webrtc 'block'",
    "form-action 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    "manifest-src 'none'",
  ].join("; ");
}
