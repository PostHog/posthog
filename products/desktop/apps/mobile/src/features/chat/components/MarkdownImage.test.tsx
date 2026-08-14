import { createElement } from "react";
import { Image } from "react-native";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { MarkdownImage } from "./MarkdownImage";

vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#777", 11: "#555" } }),
}));

vi.mock("phosphor-react-native", () => ({
  ArrowSquareOut: (props: Record<string, unknown>) =>
    createElement("ArrowSquareOut", props),
  ImageBroken: (props: Record<string, unknown>) =>
    createElement("ImageBroken", props),
}));

function render(props: {
  url: string;
  alt?: string;
  disableRemoteImages?: boolean;
}) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(MarkdownImage, props));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

describe("MarkdownImage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches image size for remote images by default", () => {
    const getSize = vi.spyOn(Image, "getSize").mockImplementation(() => {});
    render({ url: "http://127.0.0.1/secret", alt: "x" });
    expect(getSize).toHaveBeenCalledWith(
      "http://127.0.0.1/secret",
      expect.any(Function),
      expect.any(Function),
    );
  });

  it("does not fetch remote images when disableRemoteImages is set", () => {
    const getSize = vi.spyOn(Image, "getSize").mockImplementation(() => {});
    const tree = JSON.stringify(
      render({
        url: "http://127.0.0.1/secret",
        alt: "sneaky",
        disableRemoteImages: true,
      }).toJSON(),
    );
    expect(getSize).not.toHaveBeenCalled();
    // Renders a tap-to-open placeholder that shows the alt text.
    expect(tree).toContain("sneaky");
    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it("still fetches non-remote images even when disableRemoteImages is set", () => {
    const getSize = vi.spyOn(Image, "getSize").mockImplementation(() => {});
    render({
      url: "data:image/png;base64,AAAA",
      disableRemoteImages: true,
    });
    expect(getSize).toHaveBeenCalled();
  });
});
