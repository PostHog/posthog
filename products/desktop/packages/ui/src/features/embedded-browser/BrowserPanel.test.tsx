import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BrowserPanelChrome } from "./BrowserPanel";

function isDisabled(el: HTMLElement): boolean {
  return (
    el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true"
  );
}

function chromeProps(overrides = {}) {
  return {
    hasPage: false,
    currentUrl: "",
    pageState: null,
    loadError: null,
    onNavigate: vi.fn(),
    onBack: vi.fn(),
    onForward: vi.fn(),
    onReload: vi.fn(),
    onOpenExternal: vi.fn(),
    onOpenDevTools: vi.fn(),
    ...overrides,
  };
}

describe("BrowserPanelChrome", () => {
  it("shows the URL prompt for a fresh tab and disables page actions", () => {
    render(<BrowserPanelChrome {...chromeProps()} />);
    expect(screen.getByText("Open a page")).toBeTruthy();
    expect(isDisabled(screen.getByLabelText("Reload"))).toBe(true);
    expect(isDisabled(screen.getByLabelText("Open DevTools"))).toBe(true);
  });

  it("submits the typed URL on Enter", () => {
    const onNavigate = vi.fn();
    render(<BrowserPanelChrome {...chromeProps({ onNavigate })} />);
    const input = screen.getByLabelText("Page URL");
    fireEvent.change(input, { target: { value: "localhost:3000" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("localhost:3000");
  });

  it("abandons the draft on Escape without navigating", () => {
    const onNavigate = vi.fn();
    render(
      <BrowserPanelChrome
        {...chromeProps({
          onNavigate,
          hasPage: true,
          currentUrl: "https://posthog.com/",
        })}
      />,
    );
    const input = screen.getByLabelText("Page URL") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "typo" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onNavigate).not.toHaveBeenCalled();
    expect(input.value).toBe("https://posthog.com/");
  });

  it("enables history buttons from page state", () => {
    render(
      <BrowserPanelChrome
        {...chromeProps({
          hasPage: true,
          currentUrl: "https://posthog.com/pricing",
          pageState: {
            viewId: "v",
            url: "https://posthog.com/pricing",
            title: "Pricing",
            canGoBack: true,
            canGoForward: false,
            isLoading: false,
          },
        })}
      />,
    );
    expect(isDisabled(screen.getByLabelText("Back"))).toBe(false);
    expect(isDisabled(screen.getByLabelText("Forward"))).toBe(true);
  });

  it("shows the load-failed banner with a retry", () => {
    const onReload = vi.fn();
    render(
      <BrowserPanelChrome
        {...chromeProps({
          hasPage: true,
          currentUrl: "http://localhost:3000/",
          loadError: "net::ERR_CONNECTION_REFUSED",
          onReload,
        })}
      />,
    );
    expect(screen.getByText("net::ERR_CONNECTION_REFUSED")).toBeTruthy();
    fireEvent.click(screen.getByText("Retry"));
    expect(onReload).toHaveBeenCalled();
  });
});
