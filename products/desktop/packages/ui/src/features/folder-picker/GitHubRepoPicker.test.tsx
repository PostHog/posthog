import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GitHubRepoPicker } from "./GitHubRepoPicker";

describe("GitHubRepoPicker", () => {
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
});
