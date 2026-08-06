import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import type { Components } from "react-markdown";
import { openAnnouncementCta } from "./announcementCta";

// Announcement bodies render inside a quill dialog, where the app's default
// markdown link (Radix accent color plus an external-link glyph) has no theme
// vars — the glyph draws invisibly and leaves a blank gap. Plain anchors let
// quill's own dialog-description link styling take over, and clicks route
// through the announcement CTA opener so https and posthog-code:// both work.
const announcementComponents: Partial<Components> = {
  a: ({ href, children }) => (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        if (href) openAnnouncementCta(href);
      }}
    >
      {children}
    </a>
  ),
};

export function AnnouncementMarkdown({ content }: { content: string }) {
  return (
    <MarkdownRenderer
      content={content}
      componentsOverride={announcementComponents}
    />
  );
}
