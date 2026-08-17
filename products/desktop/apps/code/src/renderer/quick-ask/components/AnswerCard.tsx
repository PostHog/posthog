import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";

const AUTOSCROLL_SLACK_PX = 48;

export function ThinkingCard({ label }: { label: string }): React.JSX.Element {
  return (
    <div className="qa-card qa-card-thinking">
      <div className="qa-thinking-header">
        <span className="qa-thinking-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        {/* Keyed so a new reasoning step slides in instead of just swapping. */}
        <span key={label} className="qa-thinking-label">
          {label}
        </span>
      </div>
      <div className="qa-skeleton qa-skeleton-line-wide" />
      <div className="qa-skeleton qa-skeleton-line" />
      <div className="qa-skeleton qa-skeleton-line-short" />
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
  onOpenInApp: () => void;
  onNewChat: () => void;
}

export function AnswerCard({
  text,
  streaming,
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

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every text growth
  useEffect(() => {
    const el = scrollRef.current;
    if (el && streaming && pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [text, streaming]);

  return (
    <div className="qa-card">
      <div ref={scrollRef} className="qa-card-scroll" onScroll={onScroll}>
        <div className="qa-answer">
          {/* The shared evidence pipeline: object tags in the agent's
              markdown resolve into live reference chips and chart cards. */}
          <MarkdownRenderer content={text} />
          {streaming && <span className="qa-caret" />}
        </div>
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
