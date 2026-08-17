import React, { useCallback, useState } from "react";
import type { MockResponse } from "../mockResponses";
import { Chart } from "./charts";

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

export function ThinkingCard({ label }: { label: string }): React.JSX.Element {
  return (
    <div className="qa-card qa-card-thinking">
      <div className="qa-thinking-label">{label}</div>
      <div className="qa-skeleton qa-skeleton-headline" />
      <div className="qa-skeleton qa-skeleton-chart" />
      <div className="qa-skeleton qa-skeleton-line" />
    </div>
  );
}

interface AnswerCardProps {
  response: MockResponse;
  onFollowUp: (question: string) => void;
  onOpenInApp: () => void;
}

export function AnswerCard({
  response,
  onFollowUp,
  onOpenInApp,
}: AnswerCardProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  const copyAnswer = useCallback((): void => {
    void navigator.clipboard.writeText(response.copyText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }, [response]);

  return (
    <div className="qa-card">
      <div className="qa-headline">
        <div className="qa-headline-main">
          <span className="qa-headline-value">{response.headline.value}</span>
          <span
            className={
              response.headline.direction === "up"
                ? "qa-delta qa-delta-up"
                : "qa-delta qa-delta-down"
            }
          >
            {response.headline.direction === "up" ? "▲" : "▼"}{" "}
            {response.headline.delta}
          </span>
        </div>
        <div className="qa-headline-label">{response.headline.label}</div>
      </div>

      <Chart chart={response.chart} />

      <div className="qa-breakdown">
        {response.breakdown.map((item) => (
          <div key={item.label} className="qa-breakdown-item">
            <span className="qa-breakdown-label">{item.label}</span>
            <span className="qa-breakdown-value">{item.value}</span>
          </div>
        ))}
      </div>

      <div className="qa-answer">
        {response.paragraphs.map((paragraph) => (
          <AnswerParagraph key={paragraph} text={paragraph} />
        ))}
      </div>

      <div className="qa-followups">
        {response.followUps.map((followUp) => (
          <button
            key={followUp}
            type="button"
            className="qa-chip"
            onClick={() => onFollowUp(followUp)}
          >
            {followUp}
          </button>
        ))}
      </div>

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
    </div>
  );
}
