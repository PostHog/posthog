import {
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

const TEXT_MAX_CHARS = __PH_MAX_FIELD_ENTRIES__;
const TEXT_FULL_MESSAGE = __PH_TEXT_FULL__;
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

const messageOf = (error) => String(error?.message ? error.message : error);

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
        textColor: caret.textColor,
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
    const line =
      parseFloat(style.lineHeight) || parseFloat(style.fontSize) || 16;
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
        textColor: caret.textColor,
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
    {
      className: `relative h-full w-full${className ? ` ${className}` : ""}`,
    },
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
      `${text}\u200b`,
    ),
    createElement(
      "div",
      { className: "pointer-events-none absolute inset-0 overflow-hidden" },
      bars.map((bar) =>
        createElement(
          "div",
          {
            key: `${bar.clientId}:${bar.top}:${bar.left}`,
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
                "ph-caret-name absolute left-0 whitespace-nowrap rounded-(--radius-sm) px-1 text-[10px] leading-4",
              style: {
                background: bar.color,
                color: bar.textColor,
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
  const initialRef = useRef(initial);
  initialRef.current = initial;
  const read = useCallback(() => {
    const value = globalThis.ph.state.peek(key);
    return value === null || value === undefined ? initialRef.current : value;
  }, [key]);
  const [value, setValue] = useState(read);
  useEffect(() => {
    setValue(read());
    return globalThis.ph.state.subscribe(key, (next) =>
      setValue(next === null || next === undefined ? initialRef.current : next),
    );
  }, [key, read]);
  const set = useCallback(
    (next) => {
      const resolved = typeof next === "function" ? next(read()) : next;
      return globalThis.ph.state.set(key, resolved);
    },
    [key, read],
  );
  return [value, set];
}

const RANGE_UNITS = { h: "HOUR", d: "DAY", w: "WEEK", m: "MONTH" };
const RANGE_NAMES = { h: "hours", d: "days", w: "weeks", m: "months" };
const DEFAULT_DATE_RANGE = { date_from: "-7d", date_to: null };
const RANGE_PATTERN = /^-(\d+)([hdwm])$/;

export function useFragmentSettings(fragmentId, defaults) {
  const defaultsRef = useRef(defaults);
  defaultsRef.current = defaults;
  const key = `settings:${String(fragmentId || "fragment")}`;
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
          defaultsRef.current,
          current && typeof current === "object" ? current : null,
          patch,
        ),
      ),
    [setStored],
  );
  return [settings, update];
}

const SKETCHPAD_DATE_RANGE_KEY = "dateRange";
const scopedRangeKey = (id) => `dateRange:${String(id)}`;

export function describeRange(range) {
  const from = range?.date_from ? String(range.date_from) : "-7d";
  const match = RANGE_PATTERN.exec(from);
  const amount = match ? Number(match[1]) : 7;
  const unit = match ? match[2] : "d";
  const clickhouseUnit = RANGE_UNITS[unit] || "DAY";
  return {
    since: `now() - INTERVAL ${amount} ${clickhouseUnit}`,
    previousSince: `now() - INTERVAL ${amount * 2} ${clickhouseUnit}`,
    label: `Last ${amount} ${RANGE_NAMES[unit] || "days"}`,
  };
}

export function useDateRange(fragmentId) {
  const all = useSketchpadFragments();
  const keys = useMemo(() => {
    const list = fragmentId
      ? holdersOf(fragmentId, all).map((holder) => scopedRangeKey(holder.id))
      : [];
    list.push(SKETCHPAD_DATE_RANGE_KEY);
    return list;
  }, [all, fragmentId]);
  const signature = keys.join("|");
  const keysRef = useRef(keys);
  keysRef.current = keys;

  const [found, setFound] = useState({
    key: SKETCHPAD_DATE_RANGE_KEY,
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
      setFound({ key: SKETCHPAD_DATE_RANGE_KEY, range: DEFAULT_DATE_RANGE });
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
    scoped: found.key !== SKETCHPAD_DATE_RANGE_KEY,
    since: parts.since,
    previousSince: parts.previousSince,
    label: parts.label,
  };
}

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

export function hogqlString(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return `'${text.split("\\").join("\\\\").split("'").join("\\'")}'`;
}

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
          columns: result?.columns || [],
          rows: result?.results || [],
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

export function useEventNames() {
  const result = useHogQL(
    "SELECT event, count() AS uses FROM events WHERE timestamp >= now() - INTERVAL 30 DAY GROUP BY event ORDER BY uses DESC LIMIT 100",
  );
  const names = useMemo(
    () =>
      result.rows
        .map((row) => (row?.[0] ? String(row[0]) : ""))
        .filter(Boolean),
    [result.rows],
  );
  return { names, loading: result.loading, error: result.error };
}

export function formatCompact(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1000000) {
    return `${(number / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (Math.abs(number) >= 1000) {
    return `${(number / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  }
  return String(number);
}

const areaOf = (box) => Math.max(1, box.w * box.h);
const boxKey = (item) => `${item.x}:${item.y}:${item.w}:${item.h}`;
const holds = __PH_CONTAINS_CENTER__;

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

export function useSketchpadFragments() {
  const [list, setList] = useState(() => globalThis.ph.board.list());
  useEffect(() => {
    const read = () => setList(globalThis.ph.board.list());
    read();
    return globalThis.ph.board.subscribe(read);
  }, []);
  return list;
}

export function useSketchpadSelection() {
  const [ids, setIds] = useState(() => globalThis.ph.board.selection());
  useEffect(() => {
    setIds(globalThis.ph.board.selection());
    return globalThis.ph.board.subscribeSelection(setIds);
  }, []);
  return ids;
}

export function useSketchpadFocus() {
  const [id, setId] = useState(() => globalThis.ph.board.focused());
  useEffect(() => {
    setId(globalThis.ph.board.focused());
    return globalThis.ph.board.subscribeFocus(setId);
  }, []);
  return id;
}

export function useSketchpadBusy() {
  const [busy, setBusy] = useState(() => globalThis.ph.board.isBusy());
  useEffect(() => {
    setBusy(globalThis.ph.board.isBusy());
    return globalThis.ph.board.subscribeBusy(setBusy);
  }, []);
  return busy;
}

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

export function useContainer(fragmentId, options) {
  const opts = options || {};
  const padding = typeof opts.padding === "number" ? opts.padding : 16;
  const header = typeof opts.header === "number" ? opts.header : 0;
  const layout = typeof opts.layout === "function" ? opts.layout : null;
  const follow = opts.follow === true;

  const all = useSketchpadFragments();
  const busy = useSketchpadBusy();
  const self = useMemo(
    () => all.find((item) => item.id === fragmentId) || null,
    [all, fragmentId],
  );

  const memberIds = useRef(null);
  const memberBoxes = useRef({});
  const children = useMemo(() => {
    if (!self) return [];
    const others = all.filter((item) => item.id !== fragmentId);
    const inside = others.filter((item) => holds(self, item));
    const mine = inside.filter((child) =>
      inside.every(
        (other) =>
          other.id === child.id ||
          areaOf(other) <= areaOf(child) ||
          !holds(other, child),
      ),
    );
    const keep = new Set(mine.map((item) => item.id));
    const before = memberIds.current;
    const boxes = memberBoxes.current;
    if (before) {
      for (const item of others) {
        if (keep.has(item.id)) continue;
        if (!before.has(item.id)) continue;
        if (boxes[item.id] !== boxKey(item)) continue;
        keep.add(item.id);
      }
    }
    const members = others.filter((item) => keep.has(item.id));
    memberIds.current = keep;
    const next = {};
    for (const item of members) next[item.id] = boxKey(item);
    memberBoxes.current = next;
    return members.sort((a, b) => a.y - b.y || a.x - b.x);
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
    if (!self) return;
    const previous = lastBox.current;
    const selfMoved =
      previous !== null &&
      (previous.x !== self.x ||
        previous.y !== self.y ||
        previous.w !== self.w ||
        previous.h !== self.h);
    if (busy && !selfMoved) return;
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
