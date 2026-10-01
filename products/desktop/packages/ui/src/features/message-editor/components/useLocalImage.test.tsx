import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const readFileAsDataUrl = vi.hoisted(() =>
  vi.fn(async () => "data:image/png;base64,AA"),
);
vi.mock("@posthog/ui/features/message-editor/hostApi", () => ({
  readFileAsDataUrl,
}));

import { useLocalImage } from "./useLocalImage";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useLocalImage", () => {
  beforeEach(() => {
    readFileAsDataUrl.mockClear();
  });

  it("reads a screenshot the composer saved", async () => {
    const path = "/tmp/posthog-code-clipboard/attachment-1/shot.png";
    const { result } = renderHook(() => useLocalImage(path), { wrapper });

    await waitFor(() =>
      expect(result.current).toBe("data:image/png;base64,AA"),
    );
    expect(readFileAsDataUrl).toHaveBeenCalledWith({ filePath: path });
  });

  it.each([
    ["a relative path", "../../Pictures/private.png"],
    [
      "an absolute path outside the clipboard folder",
      "/Users/me/Pictures/private.png",
    ],
  ])("never reads %s from message text", (_name, path) => {
    const { result } = renderHook(() => useLocalImage(path), { wrapper });

    expect(result.current).toBeNull();
    expect(readFileAsDataUrl).not.toHaveBeenCalled();
  });
});
