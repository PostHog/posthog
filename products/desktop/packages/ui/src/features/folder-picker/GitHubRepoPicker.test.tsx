import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GitHubRepoPicker } from "./GitHubRepoPicker";

describe("GitHubRepoPicker", () => {
  afterEach(() => vi.useRealTimers());

  it("loads the next page once when the results reach the scroll end", () => {
    const onLoadMore = vi.fn();
    const { container } = render(
      <GitHubRepoPicker
        value={null}
        onChange={vi.fn()}
        repositories={Array.from(
          { length: 50 },
          (_, index) => `posthog/repository-${index}`,
        )}
        isLoading={false}
        open
        onOpenChange={vi.fn()}
        searchQuery=""
        onSearchQueryChange={vi.fn()}
        hasMore
        onLoadMore={onLoadMore}
      />,
    );
    const list = container.ownerDocument.querySelector(
      "[data-slot='combobox-list']",
    );
    if (!list) {
      throw new Error("Expected the repository results list to render");
    }
    Object.defineProperties(list, {
      clientHeight: { value: 240 },
      scrollHeight: { value: 600 },
      scrollTop: { value: 360, writable: true },
    });

    fireEvent.scroll(list);
    fireEvent.scroll(list);

    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("keeps the current page in place while the next page loads", () => {
    vi.useFakeTimers();
    const firstPage = Array.from(
      { length: 50 },
      (_, index) => `posthog/repository-${index}`,
    );
    const props = {
      value: null,
      onChange: vi.fn(),
      isLoading: false,
      open: true,
      onOpenChange: vi.fn(),
      searchQuery: "",
      onSearchQueryChange: vi.fn(),
      hasMore: true,
      onLoadMore: vi.fn(),
    };
    const { container, rerender } = render(
      <GitHubRepoPicker
        {...props}
        repositories={firstPage}
        isLoadingMore={false}
      />,
    );
    const list = container.ownerDocument.querySelector(
      "[data-slot='combobox-list']",
    );
    if (!(list instanceof HTMLElement)) {
      throw new Error("Expected the repository results list to render");
    }
    Object.defineProperties(list, {
      clientHeight: { value: 360 },
      scrollHeight: { value: 600 },
      scrollTop: { value: 240, writable: true },
    });
    fireEvent.scroll(list);
    rerender(
      <GitHubRepoPicker {...props} repositories={firstPage} isLoadingMore />,
    );

    expect(screen.getByText("posthog/repository-0")).toBeInTheDocument();
    expect(screen.queryByText("Loading more")).not.toBeInTheDocument();

    act(() => vi.advanceTimersByTime(200));

    expect(screen.getByText("Loading more")).toBeInTheDocument();
    expect(list.scrollTop).toBe(240);

    list.scrollTop = 0;

    rerender(
      <GitHubRepoPicker
        {...props}
        repositories={[
          ...firstPage,
          ...Array.from(
            { length: 50 },
            (_, index) => `posthog/repository-${index + 50}`,
          ),
        ]}
        isLoadingMore={false}
      />,
    );

    expect(screen.getByText("posthog/repository-0")).toBeInTheDocument();
    expect(screen.getByText("posthog/repository-99")).toBeInTheDocument();
    expect(screen.queryByText("Loading more")).not.toBeInTheDocument();
    expect(list.scrollTop).toBe(240);
  });
});
