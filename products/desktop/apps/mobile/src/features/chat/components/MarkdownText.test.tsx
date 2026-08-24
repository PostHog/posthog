import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { MarkdownText } from "./MarkdownText";

vi.mock("./CopyButton", () => ({ CopyButton: () => null }));

vi.mock("@/features/auth", () => ({
  useAuthStore: (selector: (state: { cloudRegion: null }) => unknown) =>
    selector({ cloudRegion: null }),
  getCloudUrlFromRegion: () => null,
}));

function renderTree(content: string): string {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(MarkdownText, { content }));
  });
  if (!renderer) throw new Error("Renderer not created");
  return JSON.stringify((renderer as ReturnType<typeof create>).toJSON());
}

describe("MarkdownText", () => {
  it.each([
    {
      name: "ordered list starting at 1",
      content: "1. Alpha\n2. Beta\n3. Gamma",
      present: ["1.", "2.", "3."],
      absent: ["•"],
    },
    {
      name: "ordered list starting above 1 preserves the source numbers",
      content: "3. Alpha\n4. Beta\n5. Gamma",
      present: ["3.", "4.", "5."],
      absent: ["1.", "2."],
    },
    {
      name: "unordered list uses bullets",
      content: "- Alpha\n- Beta",
      present: ["•"],
      absent: ["1."],
    },
    {
      name: "task list uses checkboxes",
      content: "- [ ] Alpha\n- [x] Beta",
      present: ["☐", "☑"],
      absent: ["•", "1."],
    },
    {
      name: "object tag renders its label without the raw markup",
      content: 'Check the <insight id="9pQx3">checkout funnel</insight> now',
      present: ["checkout funnel", "Check the", "now"],
      absent: ["<insight", "</insight"],
    },
    {
      name: "still-streaming object tag renders nothing",
      content: 'Loading <flag id="4',
      present: ["Loading"],
      absent: ["<flag"],
    },
  ])("$name", ({ content, present, absent }) => {
    const tree = renderTree(content);
    for (const marker of present) {
      expect(tree).toContain(marker);
    }
    for (const marker of absent) {
      expect(tree).not.toContain(marker);
    }
  });
});
