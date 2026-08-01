import type { Schemas } from "@posthog/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getDesktopFileSystemShortcuts: vi.fn(),
  createDesktopFileSystemShortcut: vi.fn(),
  deleteDesktopFileSystemShortcut: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { useChannelStars, useChannelStarToggle } from "./useChannelStars";
import type { Channel } from "./useChannels";

function shortcut(
  id: string,
  type: string,
  ref: string | null,
): Schemas.FileSystemShortcut {
  return {
    id,
    path: ref?.replace(/^\/+/, "") ?? "x",
    type,
    ref,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function channel(id: string, name: string, path: string): Channel {
  return { id, name, path };
}

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useChannelStars", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("maps folder shortcuts by ref, ignoring other types and ref-less rows", async () => {
    mockClient.getDesktopFileSystemShortcuts.mockResolvedValue([
      shortcut("s1", "folder", "/alpha"),
      shortcut("s2", "insight", "abc"), // not a channel
      shortcut("s3", "folder", null), // no ref to link
    ]);

    const { result } = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect([...result.current.starredRefToShortcutId.entries()]).toEqual([
      ["/alpha", "s1"],
    ]);
  });

  it("stars an unstarred channel via its raw path, updating the cache immediately", async () => {
    mockClient.getDesktopFileSystemShortcuts.mockResolvedValue([]);

    const stars = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(stars.result.current.isLoading).toBe(false));

    const created = shortcut("s1", "folder", "/alpha");
    mockClient.createDesktopFileSystemShortcut.mockResolvedValue(created);
    // Hang the refetch so only the optimistic cache write is exercised.
    mockClient.getDesktopFileSystemShortcuts.mockReturnValue(
      new Promise(() => {}),
    );

    const toggle = renderHook(
      () => useChannelStarToggle(channel("1", "alpha", "/alpha")),
      { wrapper },
    );
    expect(toggle.result.current.isStarred).toBe(false);

    await act(async () => {
      toggle.result.current.toggleStar();
    });

    expect(mockClient.createDesktopFileSystemShortcut).toHaveBeenCalledWith({
      path: "alpha",
      type: "folder",
      ref: "/alpha",
    });
    await waitFor(() =>
      expect(stars.result.current.starredRefToShortcutId.get("/alpha")).toBe(
        "s1",
      ),
    );
  });

  it("unstars a starred channel by deleting its shortcut id", async () => {
    mockClient.getDesktopFileSystemShortcuts.mockResolvedValue([
      shortcut("s1", "folder", "/alpha"),
    ]);

    const stars = renderHook(() => useChannelStars(), { wrapper });
    await waitFor(() => expect(stars.result.current.isLoading).toBe(false));

    mockClient.deleteDesktopFileSystemShortcut.mockResolvedValue(undefined);
    mockClient.getDesktopFileSystemShortcuts.mockReturnValue(
      new Promise(() => {}),
    );

    const toggle = renderHook(
      () => useChannelStarToggle(channel("1", "alpha", "/alpha")),
      { wrapper },
    );
    expect(toggle.result.current.isStarred).toBe(true);

    await act(async () => {
      toggle.result.current.toggleStar();
    });

    expect(mockClient.deleteDesktopFileSystemShortcut).toHaveBeenCalledWith(
      "s1",
    );
    await waitFor(() =>
      expect(stars.result.current.starredRefToShortcutId.has("/alpha")).toBe(
        false,
      ),
    );
  });
});
