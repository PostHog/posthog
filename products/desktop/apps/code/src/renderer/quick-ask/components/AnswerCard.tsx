import type { QuickAskChart } from "@posthog/core/quick-ask/quick-ask";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Chart } from "./charts";
import { Markdown } from "./Markdown";

const AUTOSCROLL_SLACK_PX = 48;

export function ThinkingCard({ label }: { label: string }): React.JSX.Element {
  return (
    <div className="qa-card qa-card-thinking">
      <div className="qa-thinking-label">{label}</div>
      <div className="qa-skeleton qa-skeleton-line-wide" />
      <div className="qa-skeleton qa-skeleton-line" />
    </div>
  );
}

export function ErrorCard({ message }: { message: string }): React.JSX.Element {
  return (
    <div className="qa-card">
      <div className="qa-error">{message}</div>
    </div>
  );
}

interface AnswerCardProps {
  /** Concatenated markdown of the answer so far. */
  text: string;
  /** Still receiving tokens: show the streaming caret, hold the actions. */
  streaming: boolean;
  charts: QuickAskChart[];
  /** The answer produced a visualization the panel could not render. */
  hasViz: boolean;
  onOpenInApp: () => void;
  onNewChat: () => void;
}

export function AnswerCard({
  text,
  streaming,
  charts,
  hasViz,
  onOpenInApp,
  onNewChat,
}: AnswerCardProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  const copyAnswer = useCallback((): void => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }, [text]);

  // Follow the stream, but stop if the user scrolled up to read.
  const onScroll = useCallback((): void => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < AUTOSCROLL_SLACK_PX;
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every text/chart growth
  useEffect(() => {
    const el = scrollRef.current;
    if (el && streaming && pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [text, charts.length, streaming]);

  return (
    <div className="qa-card">
      <div ref={scrollRef} className="qa-card-scroll" onScroll={onScroll}>
        <div className="qa-answer">
          <Markdown text={text} />
          {streaming && <span className="qa-caret" />}
        </div>

        {charts.map((chart, index) => (
          <Chart key={`${index}:${chart.title}`} chart={chart} />
        ))}

        {hasViz && (
          <button type="button" className="qa-viz-note" onClick={onOpenInApp}>
            <span className="qa-viz-glyph">📈</span>
            This answer includes a chart. Open in PostHog to see it.
          </button>
        )}
      </div>

      {!streaming && (
        <div className="qa-actions">
          <span className="qa-source">PostHog AI</span>
          <button type="button" className="qa-button" onClick={onNewChat}>
            New chat
          </button>
          <button type="button" className="qa-button" onClick={copyAnswer}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            className="qa-button qa-primary"
            onClick={onOpenInApp}
          >
            Open in PostHog
          </button>
        </div>
      )}
    </div>
  );
}
