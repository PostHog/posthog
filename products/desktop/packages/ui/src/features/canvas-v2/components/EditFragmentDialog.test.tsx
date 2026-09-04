import type { CanvasV2Fragment } from "@posthog/shared";
import { EDIT_FRAGMENT_SUBMIT } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EditFragmentDialog } from "./EditFragmentDialog";

vi.mock("@posthog/ui/features/skills/SkillCodeEditor", () => ({
  SkillCodeEditor: ({
    initialContent,
    onDocChanged,
  }: {
    initialContent: string;
    onDocChanged: (code: string) => void;
  }) => (
    <textarea
      aria-label="Code"
      defaultValue={initialContent}
      onChange={(event) => onDocChanged(event.target.value)}
    />
  ),
}));

describe("EditFragmentDialog", () => {
  it.each(["geometry", "code"] as const)(
    "keeps the draft when another user changes the fragment %s",
    async (change) => {
      const fragment: CanvasV2Fragment = {
        id: "note",
        title: "Note",
        x: 0,
        y: 0,
        w: 360,
        h: 240,
        z: 0,
        codeVersion: 1,
        code: "export default () => <div>Original</div>;",
      };
      const applyLocal = vi.fn();
      const props = {
        open: true,
        fragment,
        isPending: false,
        onOpenChange: vi.fn(),
        applyLocal,
      };
      const { rerender } = render(<EditFragmentDialog {...props} />);
      const draft = "export default () => <div>Draft</div>;";
      fireEvent.change(screen.getByLabelText("Code"), {
        target: { value: draft },
      });
      fireEvent.change(screen.getByDisplayValue("Note"), {
        target: { value: "Draft title" },
      });

      rerender(
        <EditFragmentDialog
          {...props}
          fragment={
            change === "geometry"
              ? { ...fragment, x: 100 }
              : { ...fragment, code: "export default () => <div>Remote</div>;" }
          }
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByText(EDIT_FRAGMENT_SUBMIT));
      });

      expect(applyLocal).toHaveBeenCalledWith([
        {
          type: "update_fragment",
          id: fragment.id,
          patch: { code: draft, title: "Draft title" },
        },
      ]);
    },
  );
});
