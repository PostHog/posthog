import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GitLabProjectPicker } from "./GitLabProjectPicker";

const pickerProps = {
  value: null,
  onChange: vi.fn(),
  projects: [],
  isLoading: false,
  loadFailed: false,
  onRetry: vi.fn(),
  missingScopes: [],
  open: true,
  onOpenChange: vi.fn(),
  searchQuery: "",
  onSearchQueryChange: vi.fn(),
};

describe("GitLabProjectPicker", () => {
  it("shows a failed load as an error with a retry, not as an empty list", () => {
    const onRetry = vi.fn();
    render(
      <GitLabProjectPicker {...pickerProps} loadFailed onRetry={onRetry} />,
    );

    expect(
      screen.queryByText(/No GitLab projects found/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Couldn't load GitLab projects/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
