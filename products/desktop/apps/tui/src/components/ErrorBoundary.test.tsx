import { describe, expect, it, vi } from "vitest";
import { renderInTerminal } from "../testing";
import { ErrorBoundary } from "./ErrorBoundary";

function Broken(): never {
  throw new Error("repos is undefined");
}

describe("ErrorBoundary", () => {
  it("shows a render error in place of the app and keeps running", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { instance, output } = renderInTerminal(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );
    let exited = false;
    void instance.waitUntilExit().then(() => {
      exited = true;
    });
    try {
      await vi.waitFor(() =>
        expect(output()).toContain("The TUI hit an error: repos is undefined"),
      );
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(exited).toBe(false);
    } finally {
      instance.unmount();
      vi.restoreAllMocks();
    }
  });
});
