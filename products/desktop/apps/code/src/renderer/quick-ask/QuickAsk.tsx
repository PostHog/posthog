import { happyHog } from "@posthog/ui/assets/hedgehogs";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnswerCard, ThinkingCard } from "./components/AnswerCard";
import { type MockResponse, pickMockResponse } from "./mockResponses";

type Phase = "idle" | "thinking" | "answered";

const THINKING_MS = 1100;
const PILL_MIN_WIDTH = 176;
const PILL_MAX_WIDTH = 448;
const PILL_TEXT_EXTRA = 46; // pill padding + caret allowance around the text

export function QuickAsk(): React.JSX.Element {
  const [phase, setPhase] = useState<Phase>("idle");
  const [response, setResponse] = useState<MockResponse | null>(null);
  const [pillWidth, setPillWidth] = useState(PILL_MIN_WIDTH);
  const inputRef = useRef<HTMLInputElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const thinkingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reset = useCallback((): void => {
    if (thinkingTimer.current) {
      clearTimeout(thinkingTimer.current);
      thinkingTimer.current = null;
    }
    setPhase("idle");
    setResponse(null);
    setPillWidth(PILL_MIN_WIDTH);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }, []);

  // Reset and refocus every time the panel is summoned.
  useEffect(() => {
    inputRef.current?.focus();
    return window.quickAsk?.onShown(() => {
      reset();
      inputRef.current?.focus();
    });
  }, [reset]);

  // Drive the BrowserWindow height from the rendered content.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new ResizeObserver(() => {
      window.quickAsk?.resize(
        Math.ceil(root.getBoundingClientRect().height) + 24,
      );
    });
    observer.observe(root);
    return () => observer.disconnect();
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

  const ask = useCallback((question: string): void => {
    const next = pickMockResponse(question);
    setResponse(next);
    setPhase("thinking");
    if (thinkingTimer.current) {
      clearTimeout(thinkingTimer.current);
    }
    thinkingTimer.current = setTimeout(() => {
      setPhase("answered");
      inputRef.current?.focus();
    }, THINKING_MS);
  }, []);

  const submit = useCallback((): void => {
    const question = inputRef.current?.value.trim();
    if (!question) return;
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    syncPillWidth();
    ask(question);
  }, [ask, syncPillWidth]);

  const followUp = useCallback(
    (question: string): void => {
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      syncPillWidth();
      ask(question);
    },
    [ask, syncPillWidth],
  );

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

  return (
    <div
      ref={rootRef}
      className="qa-root"
      onPointerEnter={enableMouse}
      onPointerLeave={disableMouse}
    >
      <div className="qa-pill-row">
        <img
          src={happyHog}
          alt=""
          draggable={false}
          className={phase === "thinking" ? "qa-hog qa-hog-thinking" : "qa-hog"}
        />
        <div className="qa-pill" style={{ width: pillWidth }}>
          <input
            ref={inputRef}
            type="text"
            placeholder={
              phase === "answered" ? "Ask a follow-up…" : "Ask PostHog AI"
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

      {phase === "thinking" && response && (
        <ThinkingCard label={response.thinkingLabel} />
      )}
      {phase === "answered" && response && (
        <AnswerCard
          response={response}
          onFollowUp={followUp}
          onOpenInApp={openInApp}
        />
      )}
    </div>
  );
}
