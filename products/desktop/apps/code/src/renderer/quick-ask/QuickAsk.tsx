import type {
  QuickAskChart,
  QuickAskEvent,
} from "@posthog/core/quick-ask/quick-ask";
import { happyHog } from "@posthog/ui/assets/hedgehogs";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnswerCard, ErrorCard, ThinkingCard } from "./components/AnswerCard";

type Phase = "idle" | "thinking" | "streaming" | "answered" | "error";

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
  const [charts, setCharts] = useState<QuickAskChart[]>([]);
  const [hasViz, setHasViz] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [pillWidth, setPillWidth] = useState(PILL_MIN_WIDTH);
  const [flip, setFlip] = useState(false);
  const conversationIdRef = useRef<string | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const reset = useCallback((): void => {
    window.quickAsk?.cancel();
    conversationIdRef.current = undefined;
    setPhase("idle");
    setThinkingLabel("Thinking…");
    setTextParts([]);
    setCharts([]);
    setHasViz(false);
    setErrorMessage("");
    setPillWidth(PILL_MIN_WIDTH);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }, []);

  // Tell the main process how tall the window should be. Called on every
  // layout-relevant change: the ResizeObserver misses re-shows because the
  // content size does not change while hidden.
  const reportSize = useCallback((): void => {
    const root = rootRef.current;
    if (!root) return;
    window.quickAsk?.resize(
      Math.ceil(root.getBoundingClientRect().height) + 24,
    );
  }, []);

  // The main process owns screen geometry: it caps the card and decides
  // whether the card sits above the pill (summoned near the screen bottom).
  useEffect(() => {
    return window.quickAsk?.onLayout((layout) => {
      document.documentElement.style.setProperty(
        "--qa-card-max",
        `${layout.cardMax}px`,
      );
      setFlip(layout.flip);
    });
  }, []);

  // Refocus on every summon. The previous session is kept — "New chat" or a
  // new question clears it — so reopening restores the last answer.
  useEffect(() => {
    inputRef.current?.focus();
    const unsubscribe = window.quickAsk?.onShown(() => {
      inputRef.current?.focus();
      reportSize();
      // Re-report once the flipped layout has settled.
      requestAnimationFrame(reportSize);
    });
    return () => unsubscribe?.();
  }, [reportSize]);

  // Answer stream from the main process.
  useEffect(() => {
    return window.quickAsk?.onEvent((raw) => {
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
        case "chart":
          setCharts((current) => [...current, event.chart]);
          setPhase((current) =>
            current === "thinking" || current === "idle"
              ? "streaming"
              : current,
          );
          break;
        case "viz":
          setHasViz(true);
          setPhase((current) =>
            current === "thinking" ? "streaming" : current,
          );
          break;
        case "error":
          setErrorMessage(event.message);
          setPhase("error");
          break;
        case "done":
          setPhase((current) => (current === "error" ? current : "answered"));
          inputRef.current?.focus();
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

  // The hedgehog is the drag handle. Native `-webkit-app-region: drag`
  // swallows the mousedown that click-through relies on, so the panel moves
  // itself: report a grab offset and the main process follows the cursor.
  const startDrag = useCallback((event: React.MouseEvent): void => {
    if (event.button !== 0) return;
    event.preventDefault();
    window.quickAsk?.dragStart({
      dx: event.screenX - window.screenX,
      dy: event.screenY - window.screenY,
    });
    const endDrag = (): void => {
      window.quickAsk?.dragEnd();
      document.removeEventListener("mouseup", endDrag);
    };
    document.addEventListener("mouseup", endDrag);
  }, []);

  // The window is click-through except while the pointer is over content.
  const enableMouse = useCallback((): void => {
    window.quickAsk?.setInteractive(true);
  }, []);
  const disableMouse = useCallback((): void => {
    window.quickAsk?.setInteractive(false);
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
    const question = inputRef.current?.value.trim();
    if (!question) return;
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    syncPillWidth();
    setTextParts([]);
    setCharts([]);
    setHasViz(false);
    setErrorMessage("");
    setThinkingLabel("Thinking…");
    setPhase("thinking");
    window.quickAsk?.ask(question, conversationIdRef.current);
  }, [syncPillWidth]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>): void => {
      if (event.key === "Enter") {
        submit();
      } else if (event.key === "Escape") {
        window.quickAsk?.hide();
      }
    },
    [submit],
  );

  const openInApp = useCallback((): void => {
    window.quickAsk?.openInApp();
  }, []);

  const answerText = textParts.map((part) => part.content).join("\n\n");

  return (
    <div
      ref={rootRef}
      className={flip ? "qa-root qa-flip" : "qa-root"}
      onPointerEnter={enableMouse}
      onPointerLeave={disableMouse}
    >
      <div className="qa-pill-row">
        <button
          type="button"
          aria-label="Drag to move the panel"
          onMouseDown={startDrag}
          className={phase === "thinking" ? "qa-hog qa-hog-thinking" : "qa-hog"}
        >
          <img src={happyHog} alt="" draggable={false} />
        </button>
        <div className="qa-pill" style={{ width: pillWidth }}>
          <input
            ref={inputRef}
            type="text"
            placeholder={
              phase === "answered" ? "Ask a follow-up…" : "Ask PostHog"
            }
            autoComplete="off"
            spellCheck={false}
            onKeyDown={onKeyDown}
            onInput={syncPillWidth}
          />
        </div>
        {/* Hidden mirror used to measure the typed text for the pill width. */}
        <span ref={measureRef} className="qa-measure" aria-hidden="true" />
      </div>

      {phase === "thinking" && <ThinkingCard label={thinkingLabel} />}
      {phase === "error" && <ErrorCard message={errorMessage} />}
      {(phase === "streaming" || phase === "answered") && (
        <AnswerCard
          text={answerText}
          streaming={phase === "streaming"}
          charts={charts}
          hasViz={hasViz}
          onOpenInApp={openInApp}
          onNewChat={reset}
        />
      )}
    </div>
  );
}
