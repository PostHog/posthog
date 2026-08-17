import { happyHog } from "@posthog/ui/assets/hedgehogs";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { type MockResponse, pickMockResponse } from "./mockResponses";

type Phase = "idle" | "thinking" | "answered";

const THINKING_MS = 1100;

/** Sparkle from the web app's PostHog AI branding (AnimatedSparkles). */
function Sparkle({ size }: { size: number }): React.JSX.Element {
  return (
    <svg
      width={size}
      height={size + 1}
      viewBox="0 0 14 15"
      className="qa-sparkle"
      role="img"
      aria-label="PostHog AI"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M7 0C7 0 6.49944 2.07875 6.08971 3.78113C5.76569 5.12694 4.77707 6.17975 3.50849 6.5303C1.9232 6.96825 0 7.50005 0 7.50005C0 7.50005 1.9232 8.03143 3.50849 8.46949C4.77707 8.82025 5.76569 9.87317 6.08971 11.2189C6.49944 12.9214 7 15 7 15C7 15 7.50056 12.9214 7.91029 11.2189C8.23441 9.87317 9.22293 8.82025 10.4918 8.46949C12.0769 8.03143 14 7.50005 14 7.50005C14 7.50005 12.0769 6.96825 10.4918 6.5303C9.22293 6.17975 8.23441 5.12694 7.91029 3.78113C7.50056 2.07875 7 0 7 0Z"
      />
    </svg>
  );
}

/** Renders `**bold**` and `##amber##` runs in a canned answer paragraph. */
function AnswerParagraph({ text }: { text: string }): React.JSX.Element {
  const parts = text.split(/(\*\*[^*]+\*\*|##[^#]+##)/g);
  return (
    <p>
      {parts.map((part, index) => {
        // Parts are a static split of a canned string; a position-derived key
        // is stable here.
        const key = `${index}:${part}`;
        if (part.startsWith("**")) {
          return <strong key={key}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("##")) {
          return (
            <span key={key} className="qa-num">
              {part.slice(2, -2)}
            </span>
          );
        }
        return <React.Fragment key={key}>{part}</React.Fragment>;
      })}
    </p>
  );
}

function Sparkline({ points }: { points: number[] }): React.JSX.Element {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const coords = points.map((point, index) => [
    (index / (points.length - 1)) * 100,
    34 - ((point - min) / range) * 30,
  ]);
  const line = coords
    .map(
      ([x, y], index) =>
        `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 100 36"
      preserveAspectRatio="none"
      role="img"
      aria-label="Trend sparkline"
    >
      <path
        d={`${line} L100 36 L0 36 Z`}
        fill="var(--qa-accent)"
        opacity={0.14}
      />
      <path
        d={line}
        fill="none"
        stroke="var(--qa-accent)"
        strokeWidth={1.6}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function QuickAsk(): React.JSX.Element {
  const [phase, setPhase] = useState<Phase>("idle");
  const [response, setResponse] = useState<MockResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const thinkingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reset = useCallback((): void => {
    if (thinkingTimer.current) {
      clearTimeout(thinkingTimer.current);
      thinkingTimer.current = null;
    }
    setPhase("idle");
    setResponse(null);
    setCopied(false);
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
    const shell = shellRef.current;
    if (!shell) return;
    const observer = new ResizeObserver(() => {
      window.quickAsk?.resize(Math.ceil(shell.getBoundingClientRect().height));
    });
    observer.observe(shell);
    return () => observer.disconnect();
  }, []);

  const submit = useCallback((): void => {
    const question = inputRef.current?.value.trim();
    if (!question) return;
    const next = pickMockResponse(question);
    setResponse(next);
    setCopied(false);
    setPhase("thinking");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    if (thinkingTimer.current) {
      clearTimeout(thinkingTimer.current);
    }
    thinkingTimer.current = setTimeout(() => {
      setPhase("answered");
      inputRef.current?.focus();
    }, THINKING_MS);
  }, []);

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

  const copyAnswer = useCallback((): void => {
    if (!response) return;
    void navigator.clipboard.writeText(response.copyText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }, [response]);

  return (
    <div ref={shellRef} className="qa-shell">
      <div className="qa-panel">
        <div className="qa-ask-row">
          <div className="qa-avatar">
            <img src={happyHog} alt="" draggable={false} />
          </div>
          <input
            ref={inputRef}
            type="text"
            placeholder={
              phase === "answered" ? "Ask follow-up" : "Ask a question"
            }
            autoComplete="off"
            spellCheck={false}
            onKeyDown={onKeyDown}
          />
          <span className="qa-esc">
            <kbd>esc</kbd>
          </span>
        </div>

        {phase !== "idle" && response && (
          <>
            <div className="qa-divider" />
            <div className="qa-answer-area">
              {phase === "thinking" ? (
                <div className="qa-thinking">
                  <span className="qa-dots">
                    <i />
                    <i />
                    <i />
                  </span>
                  <span>{response.thinkingLabel}</span>
                </div>
              ) : (
                <div className="qa-answer">
                  {response.paragraphs.map((paragraph) => (
                    <AnswerParagraph key={paragraph} text={paragraph} />
                  ))}
                  {response.sparkline && (
                    <div className="qa-spark">
                      <div className="qa-spark-label">
                        <span>{response.sparkline.label}</span>
                        <span>{response.sparkline.source}</span>
                      </div>
                      <Sparkline points={response.sparkline.points} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {phase === "answered" && response && (
          <>
            <div className="qa-footer">
              <span className="qa-source">
                <Sparkle size={13} />
                PostHog AI
              </span>
              <button type="button" className="qa-button" onClick={copyAnswer}>
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                type="button"
                className="qa-button qa-primary"
                onClick={() => window.quickAsk?.openInApp()}
              >
                Open in PostHog
              </button>
            </div>
            <div className="qa-followup-hint">
              ↵ to ask a follow-up · conversations will be saved to your PostHog
              AI history
            </div>
          </>
        )}
      </div>
    </div>
  );
}
