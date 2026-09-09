try {
  delete Navigator.prototype.sendBeacon;
} catch (_error) {
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
  } catch (_error) {
    globalThis[name] = undefined;
  }
}

const CHANNEL = __PH_CHANNEL__;
const MAX_STATE_VALUE_BYTES = __PH_MAX_STATE_BYTES__;
const post = (msg) => parent.postMessage({ channel: CHANNEL, ...msg }, "*");
const world = document.getElementById("world");

const pending = new Map();
let reqSeq = 0;
const request = (message) =>
  new Promise((resolve, reject) => {
    const id = String(++reqSeq);
    pending.set(id, { resolve, reject });
    post({ ...message, id });
  });
const call = (method, payload) =>
  request({ type: "data-request", method, payload });
const unavailable = (name) => () =>
  Promise.reject(new Error(`ph.${name} is not available on sketchpads yet`));

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
    return plain.map((value, index) => ({ id: `plain-${index}`, value }));
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
      return Promise.reject(
        new Error("ph.state.set(key, value) requires a key"),
      );
    }
    if (fieldStore.has(key)) {
      return Promise.reject(new Error(__PH_READ_ONLY_STATE__));
    }
    const next = value === undefined ? null : value;
    const json = jsonOf(next);
    if (json === null) {
      return Promise.reject(
        new Error("ph.state.set(key, value) needs a JSON value"),
      );
    }
    if (new TextEncoder().encode(json).length > MAX_STATE_VALUE_BYTES) {
      return Promise.reject(
        new Error(
          "ph.state.set(key, value) is limited to " +
            Math.floor(MAX_STATE_VALUE_BYTES / 1024) +
            " KB per value",
        ),
      );
    }
    if (writeState(key, next))
      post({ type: "state-changed", key, value: next });
    return Promise.resolve({ ok: true });
  },
  list: () =>
    Promise.resolve(Array.from(stateStore, ([key, value]) => ({ key, value }))),
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

let sketchpadBusy = false;
let selectedIds = [];
const sketchpadSubs = new Set();
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
let sketchpadNotifyQueued = false;
const notifySketchpad = () => {
  if (sketchpadNotifyQueued) return;
  sketchpadNotifyQueued = true;
  queueMicrotask(() => {
    sketchpadNotifyQueued = false;
    for (const cb of Array.from(sketchpadSubs)) {
      try {
        cb();
      } catch {}
    }
  });
};
const setBusy = (next) => {
  const value = next === true;
  if (value === sketchpadBusy) return;
  sketchpadBusy = value;
  for (const cb of Array.from(busySubs)) {
    try {
      cb(value);
    } catch {}
  }
};
const sketchpadRects = () => {
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
      dateRange: opts?.dateRange,
      variables: opts?.variables,
      refresh: opts?.refresh,
    }),
  query: (queryOrHogql, params, opts) =>
    call(
      "query",
      typeof queryOrHogql === "string"
        ? {
            hogql: queryOrHogql,
            params: params ?? {},
            refresh: opts?.refresh,
          }
        : {
            query: queryOrHogql,
            params: params ?? {},
            refresh: opts?.refresh,
          },
    ),
  capture: unavailable("capture"),
  state,
  fields,
  board: {
    list: sketchpadRects,
    subscribe: (cb) => {
      sketchpadSubs.add(cb);
      return () => sketchpadSubs.delete(cb);
    },
    isBusy: () => sketchpadBusy,
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

const resolveExternalAnchorUrl = __PH_RESOLVE_EXTERNAL_URL__;
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
    "translate(" +
    viewport.x +
    "px, " +
    viewport.y +
    "px) scale(" +
    viewport.zoom +
    ")";
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
  style.backgroundImage =
    "radial-gradient(var(--ph-grid-dot) 1px, transparent 1px)";
  style.backgroundSize = `${step}px ${step}px`;
  style.backgroundPosition = `${viewport.x}px ${viewport.y}px`;
};

const fragmentElementOf = (target) =>
  target instanceof Element ? target.closest(".fragment") : null;
const onSketchpadSurface = (target) =>
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
    if (!onSketchpadSurface(e.target)) return;
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
    if (!onSketchpadSurface(e.target)) return;
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

const ALLOWED_IMPORTS = new Set(__PH_ALLOWED_IMPORTS__);

let runtimePromise = null;
const loadRuntime = () => {
  if (runtimePromise) return runtimePromise;
  runtimePromise = Promise.all([import("react"), import("react-dom/client")])
    .then(([React, dom]) => {
      const ErrorBlock = ({ message }) =>
        React.createElement(
          "div",
          { className: "fragment-error" },
          React.createElement(
            "div",
            { className: "fragment-error-title" },
            __PH_ERROR_TITLE__,
          ),
          React.createElement("pre", null, message),
          React.createElement(
            "div",
            { className: "fragment-error-hint" },
            __PH_ERROR_HINT__,
          ),
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
            return React.createElement(ErrorBlock, {
              message: describeError(this.state.error),
            });
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
  const message = String(err?.message || err || "Unknown error");
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
    stack: err?.stack ? String(err.stack).slice(0, 50000) : undefined,
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
    el.style.left = `${((f.x - framedBox.x) / framedBox.w) * 100}%`;
    el.style.top = `${((f.y - framedBox.y) / framedBox.h) * 100}%`;
    el.style.width = `${(f.w / framedBox.w) * 100}%`;
    el.style.height = `${(f.h / framedBox.h) * 100}%`;
    return;
  }
  el.style.left = `${f.x}px`;
  el.style.top = `${f.y}px`;
  el.style.width = `${f.w}px`;
  el.style.height = `${f.h}px`;
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
    title.textContent = __PH_ERROR_TITLE__;
    const pre = document.createElement("pre");
    pre.textContent = message;
    const hint = document.createElement("div");
    hint.className = "fragment-error-hint";
    hint.textContent = __PH_ERROR_HINT__;
    block.append(title, pre, hint);
    entry.el.append(block);
  }
};
const activeSources = new Map();
const releaseSource = (entry) => {
  if (!entry.sourceRef) return;
  const count = activeSources.get(entry.sourceRef) - 1;
  if (count) activeSources.set(entry.sourceRef, count);
  else activeSources.delete(entry.sourceRef);
  entry.sourceRef = null;
};
const compileFragment = __PH_CREATE_COMPILER__(async (refs) => {
  const active = refs.filter((ref) => activeSources.has(ref));
  const results = active.length
    ? await request({ type: "compile-request", refs: active })
    : {};
  for (const ref of refs) {
    if (!activeSources.has(ref))
      results[ref] = { error: "The fragment source changed." };
  }
  return results;
});
const libraries = new Map();
const loadLibrary = (name) => {
  if (!ALLOWED_IMPORTS.has(name))
    throw new Error(`Unsupported fragment import: ${name}`);
  if (!libraries.has(name))
    libraries.set(
      name,
      import(name).catch((error) => {
        libraries.delete(name);
        throw error;
      }),
    );
  return libraries.get(name);
};
const executeFragment = async (artifact) => {
  if (artifact.error) throw new Error(artifact.error);
  const dependencies = new Map(
    await Promise.all(
      artifact.imports.map(async (name) => [name, await loadLibrary(name)]),
    ),
  );
  return new Promise((resolve, reject) => {
    const key = `__sketchpadModule_${crypto.randomUUID().replaceAll("-", "")}`;
    const entry = {
      started: false,
      require: (name) => {
        if (!dependencies.has(name))
          throw new Error(`Unsupported fragment import: ${name}`);
        return dependencies.get(name);
      },
      exports: {},
      resolve,
      reject,
    };
    const script = document.createElement("script");
    globalThis[key] = entry;
    const slot = `globalThis[${JSON.stringify(key)}]`;
    script.textContent =
      slot +
      ".started = true; (async function(require, exports) {\n" +
      artifact.code +
      "\nreturn exports; })(" +
      slot +
      ".require, " +
      slot +
      ".exports).then(" +
      slot +
      ".resolve, " +
      slot +
      ".reject);";
    try {
      document.head.append(script);
      if (!entry.started)
        reject(new Error("The compiled fragment could not start."));
    } finally {
      delete globalThis[key];
      script.remove();
    }
  });
};
const mount = async (entry, fragment) => {
  const seq = ++entry.mountSeq;
  releaseSource(entry);
  const id = fragment.id;
  try {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(fragment.code),
    );
    if (seq !== entry.mountSeq) return;
    const ref = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    entry.sourceRef = ref;
    activeSources.set(ref, (activeSources.get(ref) || 0) + 1);
    const artifact = await compileFragment(ref);
    if (seq !== entry.mountSeq) return;
    const mod = await executeFragment(artifact);
    if (seq !== entry.mountSeq) return;
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
  if (fragment.code === undefined) {
    if (!entry) return;
    fragment = { ...fragment, code: entry.code };
  }
  if (!entry) {
    const el = document.createElement("div");
    el.className = "fragment";
    if (fragment.surface === "plain") el.classList.add("fragment-plain");
    el.dataset.id = fragment.id;
    world.appendChild(el);
    entry = {
      el,
      root: null,
      codeVersion: null,
      code: null,
      mountSeq: 0,
      errored: false,
      fragment: null,
    };
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
  notifySketchpad();
  applyGeometry(entry.el, fragment);
  if (before && before.hidden === true && fragment.hidden !== true) {
    entry.el.classList.remove("entering");
    void entry.el.offsetWidth;
    entry.el.classList.add("entering");
  }
  entry.el.classList.toggle("fragment-plain", fragment.surface === "plain");
  entry.el.classList.toggle("focused", fragment.id === focusedId);
  if (focusedId !== null) applyFocus();
  if (
    entry.codeVersion === fragment.codeVersion &&
    entry.code === fragment.code
  )
    return;
  entry.codeVersion = fragment.codeVersion;
  entry.code = fragment.code;
  void mount(entry, fragment);
};
const remove = (id) => {
  const entry = fragments.get(id);
  if (!entry) return;
  fragments.delete(id);
  releaseSource(entry);
  entry.mountSeq += 1;
  if (entry.root) entry.root.unmount();
  entry.el.remove();
  notifySketchpad();
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
window.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" &&
    event.isTrusted &&
    !event.defaultPrevented &&
    !event.isComposing &&
    focusedId !== null
  ) {
    event.preventDefault();
    post({ type: "exit-focus" });
  }
});
let framedBox = null;
const boxHolds = __PH_CONTAINS_CENTER__;
const applyFocus = () => {
  const target = focusedId === null ? null : fragments.get(focusedId);
  const box = target?.fragment ? target.fragment : null;
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
