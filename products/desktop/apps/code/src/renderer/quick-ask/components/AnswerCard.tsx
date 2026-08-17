import type React from "react";
import { useCallback, useState } from "react";
import { Markdown } from "./Markdown";

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
  /** The answer produced a visualization the panel cannot render. */
  hasViz: boolean;
  onOpenInApp: () => void;
}

export function AnswerCard({
  text,
  streaming,
  hasViz,
  onOpenInApp,
}: AnswerCardProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  const copyAnswer = useCallback((): void => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }, [text]);

  return (
    <div className="qa-card">
      <div className="qa-answer">
        <Markdown text={text} />
        {streaming && <span className="qa-caret" />}
      </div>

      {hasViz && (
        <button type="button" className="qa-viz-note" onClick={onOpenInApp}>
          <span className="qa-viz-glyph">📈</span>
          This answer includes a chart. Open in PostHog to see it.
        </button>
      )}

      {!streaming && (
        <div className="qa-actions">
          <span className="qa-source">PostHog AI</span>
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
