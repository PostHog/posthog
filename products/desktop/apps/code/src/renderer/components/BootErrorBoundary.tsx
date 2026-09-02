import { DARK_APP_BACKGROUND_COLOR } from "@posthog/shared/constants";
import { logger } from "@posthog/ui/shell/logger";
import React, { useEffect, useRef } from "react";

const log = logger.scope("boot-error");

// Inline styles intentionally: this screen must render even when the app's
// theme, CSS or design-system providers failed to load during a boot failure.
const screenStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  outline: "none",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 16,
  padding: 24,
  backgroundColor: DARK_APP_BACKGROUND_COLOR,
  color: "#fafafa",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  textAlign: "center",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 18,
  fontWeight: 600,
};

const messageStyle: React.CSSProperties = {
  margin: 0,
  maxWidth: 480,
  fontSize: 13,
  opacity: 0.8,
};

const buttonStyle: React.CSSProperties = {
  padding: "6px 16px",
  fontSize: 13,
  fontWeight: 500,
  color: DARK_APP_BACKGROUND_COLOR,
  backgroundColor: "#fafafa",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
};

export function BootErrorScreen({ error }: { error: unknown }) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Move focus to the alert on mount so screen readers announce it and keyboard
  // users land on it, even when it is the very first thing rendered.
  useEffect(() => {
    containerRef.current?.focus();
  }, []);
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div ref={containerRef} role="alert" tabIndex={-1} style={screenStyle}>
      <h1 style={titleStyle}>PostHog failed to start</h1>
      <p style={messageStyle}>{message}</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={buttonStyle}
      >
        Reload
      </button>
    </div>
  );
}

interface BootErrorBoundaryProps {
  children: React.ReactNode;
}

interface BootErrorBoundaryState {
  error: Error | null;
}

export class BootErrorBoundary extends React.Component<
  BootErrorBoundaryProps,
  BootErrorBoundaryState
> {
  state: BootErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BootErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    log.error("Renderer crashed during render", error, info.componentStack);
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return <BootErrorScreen error={this.state.error} />;
    }
    return this.props.children;
  }
}
