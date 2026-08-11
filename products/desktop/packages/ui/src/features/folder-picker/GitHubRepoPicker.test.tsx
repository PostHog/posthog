import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GitHubRepoPicker } from "./GitHubRepoPicker";

const repositories = Array.from(
  { length: 50 },
  (_, index) => `posthog/repository-${index}`,
);

const pickerProps = {
  value: null,
  onChange: vi.fn(),
  repositories,
  isLoading: false,
  open: true,
  onOpenChange: vi.fn(),
  searchQuery: "",
  onSearchQueryChange: vi.fn(),
  hasMore: true,
};

describe("GitHubRepoPicker", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("loads the next page only when the load more button is clicked", () => {
    const onLoadMore = vi.fn();
    const { container } = render(
      <GitHubRepoPicker {...pickerProps} onLoadMore={onLoadMore} />,
    );
    const list = container.ownerDocument.querySelector(
      "[data-slot='combobox-list']",
    );
    if (!list) {
      throw new Error("Expected the repository results list to render");
    }

    fireEvent.scroll(list);
    expect(onLoadMore).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Load more repositories"));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("keeps results visible and delays the load more spinner", () => {
    vi.useFakeTimers();
    const onLoadMore = vi.fn();
    const { rerender } = render(
      <GitHubRepoPicker {...pickerProps} onLoadMore={onLoadMore} />,
    );
    const loadMoreButton = screen
      .getByText("Load more repositories")
      .closest("button");
    if (!loadMoreButton) {
      throw new Error("Expected the load more button to render");
    }

    fireEvent.click(loadMoreButton);
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    rerender(
      <GitHubRepoPicker
        {...pickerProps}
        isLoadingMore
        onLoadMore={onLoadMore}
      />,
    );

    expect(screen.getByText("posthog/repository-0")).toBeInTheDocument();
    expect(screen.queryByText("Loading repositories")).not.toBeInTheDocument();
    expect(loadMoreButton).toHaveAttribute("aria-disabled", "true");
    expect(loadMoreButton).not.toHaveAttribute("data-loading");

    act(() => vi.advanceTimersByTime(200));

    expect(loadMoreButton).toHaveAttribute("data-loading", "true");

    rerender(
      <GitHubRepoPicker
        {...pickerProps}
        repositories={[
          ...repositories,
          ...Array.from(
            { length: 50 },
            (_, index) => `posthog/repository-${index + 50}`,
          ),
        ]}
        isLoading={false}
        isLoadingMore={false}
        onLoadMore={onLoadMore}
      />,
    );

    expect(screen.getByText("posthog/repository-99")).toBeInTheDocument();
    expect(loadMoreButton).not.toHaveAttribute("data-loading");
  });
});
