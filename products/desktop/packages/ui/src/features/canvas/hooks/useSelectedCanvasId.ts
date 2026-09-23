import { useMatch } from "@tanstack/react-router";

export function useSelectedCanvasId(): string | undefined {
  return useMatch({
    from: "/_shell/canvases",
    shouldThrow: false,
    select: (match) => match.search.canvas,
  });
}
