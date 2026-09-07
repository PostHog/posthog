import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PendingChatView } from "./PendingChatView";

class ResizeObserverCapture {
  static instances: ResizeObserverCallback[] = [];

  constructor(callback: ResizeObserverCallback) {
    ResizeObserverCapture.instances.push(callback);
  }

  observe() {}
  unobserve() {}
  disconnect() {}
}

function measure(element: HTMLElement, overflow: boolean): void {
  Object.defineProperty(element, "scrollHeight", {
    configurable: true,
    value: overflow ? 500 : 100,
  });
  Object.defineProperty(element, "clientHeight", {
    configurable: true,
    value: 100,
  });
  for (const callback of ResizeObserverCapture.instances) {
    callback([], {} as ResizeObserver);
  }
}

function renderPending(
  props: {
    content?: string;
    attachments?: { id: string; label: string }[];
    statusText?: string;
  } = {},
) {
  render(
    <Theme>
      <PendingChatView
        content={props.content ?? "Ship the login fix"}
        attachments={props.attachments}
        statusText={props.statusText}
      />
    </Theme>,
  );
}

describe("PendingChatView", () => {
  beforeEach(() => {
    ResizeObserverCapture.instances = [];
    vi.stubGlobal("ResizeObserver", ResizeObserverCapture);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the prompt as a chat message with the default status", () => {
    renderPending();
    expect(screen.getByText("Ship the login fix")).toBeInTheDocument();
    expect(screen.getByText("Starting task...")).toBeInTheDocument();
  });

  it("shows the live run status in place of the default line", () => {
    renderPending({ statusText: "Starting the sandbox…" });
    expect(screen.getByText("Starting the sandbox…")).toBeInTheDocument();
    expect(screen.queryByText("Starting task...")).not.toBeInTheDocument();
  });

  it("renders file mentions as chips so the bubble matches the live transcript", () => {
    renderPending({
      content: 'fix <file path="src/a.ts" />',
    });
    expect(screen.getByText("src/a.ts")).toBeInTheDocument();
    expect(screen.queryByText("fix @src/a.ts")).not.toBeInTheDocument();
  });

  it("hides attachment chips when the content already carries file mentions", () => {
    renderPending({
      content: 'run this <file path="src/a.ts" />',
      attachments: [{ id: "src/a.ts", label: "src/a.ts" }],
    });
    expect(screen.getByText("src/a.ts")).toBeInTheDocument();
    // The attachment would render the same label a second time.
    expect(screen.getAllByText("src/a.ts")).toHaveLength(1);
  });

  it("shows attachments for plain content without file mentions", () => {
    renderPending({
      content: "summarize this",
      attachments: [{ id: "notes.txt", label: "notes.txt" }],
    });
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
  });

  it("clamps a long prompt to five lines and expands on Show more", async () => {
    renderPending({
      content: Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n\n"),
    });

    const clamped = document.querySelector(".max-h-\\[5lh\\]");
    expect(clamped).not.toBeNull();
    expect(screen.queryByText("Show more")).not.toBeInTheDocument();

    measure(clamped as HTMLElement, true);
    await waitFor(() =>
      expect(screen.getByText("Show more")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("Show more"));
    expect(screen.getByText("Show less")).toBeInTheDocument();
    expect(document.querySelector(".max-h-\\[5lh\\]")).toBeNull();
  });

  it("keeps a short prompt unclamped with no toggle", () => {
    renderPending({ content: "Ship the login fix" });

    const clamped = document.querySelector(".max-h-\\[5lh\\]");
    expect(clamped).not.toBeNull();
    measure(clamped as HTMLElement, false);
    expect(screen.queryByText("Show more")).not.toBeInTheDocument();
  });
});
