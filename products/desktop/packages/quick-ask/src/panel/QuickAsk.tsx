import {
  builderHog,
  explorerHog,
  happyHog,
  hogzillaHog,
  loopHog,
} from "@posthog/ui/assets/hedgehogs";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { QuickAskEvent } from "../service/quick-ask";
import { AnswerCard, ErrorCard, ThinkingCard } from "./components/AnswerCard";
import { quickAskHost } from "./host-bridge";

type Phase = "idle" | "thinking" | "streaming" | "answered" | "error";

/** Double-clicking the hedgehog cycles through the crew. */
const HEDGEHOGS = [happyHog, builderHog, explorerHog, loopHog];

/** Sustained shaking summons (and later banishes) hogzilla. */
const HOGZILLA_SHAKES = 5;
/** Longest pause between shakes that still counts as one long shake. */
const HOGZILLA_GAP_MS = 1_500;

/** An empty, untouched panel folds into mini mode after this long. */
const IDLE_COLLAPSE_MS = Number(
  new URLSearchParams(window.location.search).get("idleCollapse") ?? 60_000,
);

const PILL_MIN_WIDTH = 176;
const PILL_MAX_WIDTH = 448;
const PILL_TEXT_EXTRA = 46; // pill padding + caret allowance around the text

interface TextPart {
  id: string;
  content: string;
  complete: boolean;
}

/**
 * Applies a streamed text snapshot: replace by id, or let a completed message
 * take over the trailing in-progress (`temp-` id) snapshot it finalizes.
 */
function applyTextEvent(
  parts: TextPart[],
  event: { id: string; content: string; complete: boolean },
): TextPart[] {
  const byId = parts.findIndex((part) => part.id === event.id);
  if (byId >= 0) {
    return parts.map((part, index) =>
      index === byId ? { ...part, ...event } : part,
    );
  }
  if (event.complete) {
    const lastIncomplete = parts.findLastIndex((part) => !part.complete);
    if (lastIncomplete >= 0) {
      return parts.map((part, index) =>
        index === lastIncomplete ? { ...event } : part,
      );
    }
  }
  return [...parts, { ...event }];
}

export function QuickAsk(): React.JSX.Element {
  const [phase, setPhase] = useState<Phase>("idle");
  const [thinkingLabel, setThinkingLabel] = useState("Thinking…");
  const [textParts, setTextParts] = useState<TextPart[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [pillWidth, setPillWidth] = useState(PILL_MIN_WIDTH);
  const [flip, setFlip] = useState(false);
  const [hedgehog, setHedgehog] = useState(0);
  const [mini, setMini] = useState(false);
  const [hogzilla, setHogzilla] = useState(false);
  const shakeStreak = useRef({ count: 0, last: 0 });
  const [attachment, setAttachment] = useState<string | null>(null);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [canOpenSettings, setCanOpenSettings] = useState(false);
  const conversationIdRef = useRef<string | undefined>(undefined);
  const historyRef = useRef<string[]>([]);
  /** Position while walking history with the arrows; null = editing the draft. */
  const historyIndexRef = useRef<number | null>(null);
  const draftRef = useRef("");
  const inputRef = useRef<HTMLInputElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const reset = useCallback((): void => {
    quickAskHost()?.reset();
    conversationIdRef.current = undefined;
    setAttachment(null);
    setAttachError(null);
    setPhase("idle");
    setThinkingLabel("Thinking…");
    setTextParts([]);
    setErrorMessage("");
    setPillWidth(PILL_MIN_WIDTH);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    // After the re-render: the click left focus on the new-chat button.
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  // Tell the main process how tall the window should be. Called on every
  // layout-relevant change: the ResizeObserver misses re-shows because the
  // content size does not change while hidden.
  const reportSize = useCallback((): void => {
    const root = rootRef.current;
    if (!root) return;
    // The window's bounds hug this measurement: everything outside the
    // content is not part of the window at all, so clicks land on whatever
    // is behind without any click-through machinery. +2 mirrors the -2
    // slack in the root's max-height so the reported height never exceeds
    // the space the main process said was available.
    const rect = root.getBoundingClientRect();
    quickAskHost()?.resize({
      width: Math.ceil(rect.width) + 2,
      height: Math.ceil(rect.height) + 2,
    });
  }, []);

  // The main process owns screen geometry: it pushes the room available at
  // the current position and decides whether the card sits above the pill
  // (summoned near the screen bottom). The root caps itself to that room and
  // flexbox shrinks the card into whatever is left, so the card cap never
  // depends on the measured height it feeds back.
  useEffect(() => {
    return quickAskHost()?.onLayout((layout) => {
      document.documentElement.style.setProperty(
        "--qa-root-max",
        `${Math.max(60, layout.maxHeight - 2)}px`,
      );
      setFlip(layout.flip);
      requestAnimationFrame(reportSize);
    });
  }, [reportSize]);

  const loading = phase === "thinking" || phase === "streaming";

  // Refocus on every summon. The previous session is kept — "New chat" or a
  // new question clears it — so reopening restores the last answer.
  useEffect(() => {
    const unsubscribe = quickAskHost()?.onShown(() => {
      // Summoning is an intent to type; leave mini mode.
      setMini(false);
      inputRef.current?.focus();
      reportSize();
      // Re-report once the flipped layout has settled.
      requestAnimationFrame(reportSize);
    });
    return () => unsubscribe?.();
  }, [reportSize]);

  // Esc dismisses from anywhere.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        quickAskHost()?.hide();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Answer stream from the main process.
  useEffect(() => {
    return quickAskHost()?.onEvent((raw) => {
      const event = raw as QuickAskEvent;
      switch (event.type) {
        case "conversation":
          conversationIdRef.current = event.conversationId;
          break;
        case "reasoning":
          setThinkingLabel(event.content || "Thinking…");
          break;
        case "text":
          setTextParts((parts) => applyTextEvent(parts, event));
          setPhase((current) =>
            current === "thinking" || current === "idle"
              ? "streaming"
              : current,
          );
          break;
        case "error":
          setErrorMessage(event.message);
          setPhase("error");
          break;
        case "done":
          setPhase((current) => (current === "error" ? current : "answered"));
          break;
      }
    });
  }, []);

  // Drive the BrowserWindow height from the rendered content.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new ResizeObserver(reportSize);
    observer.observe(root);
    return () => observer.disconnect();
  }, [reportSize]);

  // Screenshot lifecycle: the main process owns the bytes and reports the
  // chip preview (or why capture failed) here.
  useEffect(() => {
    return quickAskHost()?.onAttachment((payload) => {
      const { previewDataUrl, error, canOpenSettings } = (payload ?? {}) as {
        previewDataUrl?: string | null;
        error?: string;
        canOpenSettings?: boolean;
      };
      setAttachment(previewDataUrl ?? null);
      setAttachError(error ?? null);
      setCanOpenSettings(canOpenSettings ?? false);
    });
  }, []);

  useEffect(() => {
    if (!attachError) return;
    // A permission miss carries a settings link; leave it up until acted on.
    if (canOpenSettings) return;
    const timer = setTimeout(() => setAttachError(null), 5000);
    return () => clearTimeout(timer);
  }, [attachError, canOpenSettings]);

  // The hedgehog is the drag handle. Native `-webkit-app-region: drag`
  // swallows the mousedown that click-through relies on, so the panel moves
  // itself: report a grab offset and the main process follows the cursor.
  const startDrag = useCallback((event: React.MouseEvent): void => {
    if (event.button !== 0) return;
    event.preventDefault();
    quickAskHost()?.dragStart({
      dx: event.screenX - window.screenX,
      dy: event.screenY - window.screenY,
    });
    const endDrag = (): void => {
      quickAskHost()?.dragEnd();
      document.removeEventListener("mouseup", endDrag);
    };
    document.addEventListener("mouseup", endDrag);
  }, []);

  // Figma-style pill: width hugs the typed text.
  const syncPillWidth = useCallback((): void => {
    const measure = measureRef.current;
    const input = inputRef.current;
    if (!measure || !input) return;
    measure.textContent = input.value || input.placeholder;
    const width = Math.min(
      Math.max(measure.offsetWidth + PILL_TEXT_EXTRA, PILL_MIN_WIDTH),
      PILL_MAX_WIDTH,
    );
    setPillWidth(width);
  }, []);

  const submit = useCallback((): void => {
    // A turn is already streaming: ignore type-ahead so a second question can't
    // relay onto the live run and corrupt turn attribution. The input is also
    // disabled, but this closes the click-race before React applies that.
    if (loading) return;
    const question = inputRef.current?.value.trim();
    if (!question) return;
    // Shell-style history for the up/down arrows.
    const history = historyRef.current;
    if (history[history.length - 1] !== question) {
      history.push(question);
    }
    historyIndexRef.current = null;
    draftRef.current = "";
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    syncPillWidth();
    setTextParts([]);
    setErrorMessage("");
    setThinkingLabel("Thinking…");
    setPhase("thinking");
    // The main process folds the pending screenshot into this ask.
    setAttachment(null);
    quickAskHost()?.ask(question, conversationIdRef.current);
  }, [syncPillWidth, loading]);

  // Up/down arrows recall previously sent questions, shell-style: up walks
  // back through history, down walks forward and lands on the unsent draft.
  const recallHistory = useCallback(
    (direction: -1 | 1): void => {
      const input = inputRef.current;
      if (!input) return;
      const history = historyRef.current;
      if (history.length === 0) return;
      let index = historyIndexRef.current;
      if (index === null) {
        if (direction === 1) return; // Nothing newer than the draft.
        draftRef.current = input.value;
        index = history.length - 1;
      } else {
        index += direction;
      }
      if (index >= history.length) {
        historyIndexRef.current = null;
        input.value = draftRef.current;
      } else {
        historyIndexRef.current = Math.max(0, index);
        input.value = history[historyIndexRef.current];
      }
      input.setSelectionRange(input.value.length, input.value.length);
      syncPillWidth();
    },
    [syncPillWidth],
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>): void => {
      if (event.key === "Enter") {
        submit();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        recallHistory(-1);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        recallHistory(1);
      }
    },
    [submit, recallHistory],
  );

  const openInApp = useCallback((): void => {
    quickAskHost()?.openInApp();
  }, []);

  const nextHedgehog = useCallback((): void => {
    setHedgehog((current) => (current + 1) % HEDGEHOGS.length);
  }, []);

  // Shaking the panel while dragging it cycles the hedgehog. Keeping the
  // shake going summons hogzilla; another long shake calms it back down.
  const onShake = useCallback((): void => {
    const now = Date.now();
    const streak = shakeStreak.current;
    streak.count = now - streak.last < HOGZILLA_GAP_MS ? streak.count + 1 : 1;
    streak.last = now;
    if (streak.count >= HOGZILLA_SHAKES) {
      streak.count = 0;
      setHogzilla((current) => !current);
      return;
    }
    if (!hogzilla) {
      nextHedgehog();
    }
  }, [hogzilla, nextHedgehog]);

  useEffect(() => {
    const unsubscribe = quickAskHost()?.onShake(onShake);
    return () => unsubscribe?.();
  }, [onShake]);

  const toggleMini = useCallback((): void => {
    setMini((current) => !current);
  }, []);

  // Left open, empty, and untouched, the panel folds itself into mini mode.
  useEffect(() => {
    if (mini || hogzilla || phase !== "idle") return;
    let timer: number;
    const schedule = (): void => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (inputRef.current?.value) {
          schedule();
        } else {
          setMini(true);
        }
      }, IDLE_COLLAPSE_MS);
    };
    schedule();
    window.addEventListener("keydown", schedule);
    window.addEventListener("mousedown", schedule);
    window.addEventListener("mousemove", schedule);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", schedule);
      window.removeEventListener("mousedown", schedule);
      window.removeEventListener("mousemove", schedule);
    };
  }, [mini, hogzilla, phase]);

  // Put the caret back in the pill when leaving mini mode, and when a turn
  // settles and re-enables the input (a disabled input drops focus and the
  // browser does not restore it).
  useEffect(() => {
    if (!mini && !loading) {
      inputRef.current?.focus();
    }
  }, [mini, loading]);

  const status = loading
    ? "busy"
    : phase === "answered"
      ? "ready"
      : phase === "error"
        ? "error"
        : "idle";

  return (
    <div
      ref={rootRef}
      className={[
        "qa-root",
        flip && "qa-flip",
        mini && "qa-mini",
        hogzilla && "qa-zilla",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="qa-pill-row">
        <button
          type="button"
          aria-label={
            hogzilla
              ? "Hogzilla — shake to calm it down"
              : mini
                ? "Expand the panel"
                : "Drag to move the panel"
          }
          onMouseDown={startDrag}
          onDoubleClick={hogzilla ? undefined : toggleMini}
          className={phase === "thinking" ? "qa-hog qa-hog-thinking" : "qa-hog"}
        >
          <img
            src={hogzilla ? hogzillaHog : HEDGEHOGS[hedgehog]}
            alt=""
            draggable={false}
          />
          <span
            className={`qa-status qa-status-${status}`}
            aria-hidden="true"
          />
        </button>
        {mini && loading && (
          <span key={thinkingLabel} className="qa-mini-label">
            {thinkingLabel}
          </span>
        )}
        <div className="qa-pill" style={{ width: pillWidth }}>
          <input
            ref={inputRef}
            type="text"
            placeholder={
              phase === "answered" ? "Ask a follow-up…" : "Ask PostHog"
            }
            autoComplete="off"
            spellCheck={false}
            disabled={loading}
            onKeyDown={onKeyDown}
            onInput={syncPillWidth}
          />
        </div>
        {phase !== "idle" && (
          <button
            type="button"
            aria-label="New chat"
            title="New chat"
            className="qa-new"
            onClick={reset}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 10 10"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M5 1.5V8.5M1.5 5H8.5" />
            </svg>
          </button>
        )}
        <button
          type="button"
          aria-label="Capture screen"
          title="Capture and annotate the screen"
          className="qa-shot"
          onClick={() => quickAskHost()?.capture()}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M1.5 4.5a1 1 0 0 1 1-1h1.6l1-1.5h3.8l1 1.5h1.6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1z" />
            <circle cx="7" cy="7.2" r="2.2" />
          </svg>
        </button>
        <button
          type="button"
          aria-label="Close"
          title="Close"
          className="qa-close"
          onClick={() => quickAskHost()?.hide()}
        >
          <svg
            width="13"
            height="13"
            viewBox="0 0 10 10"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M1.5 1.5L8.5 8.5M8.5 1.5L1.5 8.5" />
          </svg>
        </button>
        {/* Hidden mirror used to measure the typed text for the pill width. */}
        <span ref={measureRef} className="qa-measure" aria-hidden="true" />
      </div>

      {(attachment || attachError) && (
        <div className="qa-attach">
          {attachment ? (
            <>
              <img src={attachment} alt="Screenshot to attach" />
              <span className="qa-attach-label">Screenshot attached</span>
              <button
                type="button"
                aria-label="Remove screenshot"
                onClick={() => {
                  quickAskHost()?.discardAttachment();
                  setAttachment(null);
                }}
              >
                ×
              </button>
            </>
          ) : (
            <>
              <span className="qa-attach-error">{attachError}</span>
              {canOpenSettings && (
                <button
                  type="button"
                  className="qa-attach-settings"
                  onClick={() => {
                    quickAskHost()?.openScreenSettings();
                    setAttachError(null);
                  }}
                >
                  Open settings
                </button>
              )}
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => setAttachError(null)}
              >
                ×
              </button>
            </>
          )}
        </div>
      )}

      {phase === "thinking" && <ThinkingCard label={thinkingLabel} />}
      {phase === "error" && <ErrorCard message={errorMessage} />}
      {(phase === "streaming" || phase === "answered") && (
        <AnswerCard
          parts={textParts}
          streaming={phase === "streaming"}
          statusLabel={phase === "streaming" ? thinkingLabel : null}
          onOpenInApp={openInApp}
        />
      )}
    </div>
  );
}
