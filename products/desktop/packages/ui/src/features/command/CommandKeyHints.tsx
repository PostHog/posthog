import { Kbd, KbdGroup } from "@posthog/quill";

export function CommandKeyHints() {
  return (
    <div className="flex items-center justify-center gap-4 border-border border-t py-1">
      <div className="flex items-center gap-2">
        <KbdGroup>
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd>
        </KbdGroup>
        <span className="text-xs">navigate</span>
      </div>
      <div className="flex items-center gap-2">
        <KbdGroup>
          <Kbd>↵</Kbd>
        </KbdGroup>
        <span className="text-xs">select</span>
      </div>
      <div className="flex items-center gap-2">
        <KbdGroup>
          <Kbd>Esc</Kbd>
        </KbdGroup>
        <span className="text-xs">close</span>
      </div>
    </div>
  );
}
