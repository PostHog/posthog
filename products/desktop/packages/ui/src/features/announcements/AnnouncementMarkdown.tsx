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
      className="underline underline-offset-2"
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

// Block elements collapse to their inline content so the result fits a
// single truncating line.
const inlineComponents: Partial<Components> = {
  ...announcementComponents,
  p: ({ children }) => <>{children}</>,
  h1: ({ children }) => <>{children}</>,
  h2: ({ children }) => <>{children}</>,
  h3: ({ children }) => <>{children}</>,
  h4: ({ children }) => <>{children}</>,
  h5: ({ children }) => <>{children}</>,
  h6: ({ children }) => <>{children}</>,
  blockquote: ({ children }) => <>{children}</>,
  ul: ({ children }) => <>{children}</>,
  ol: ({ children }) => <>{children}</>,
  li: ({ children }) => <>{children}</>,
  hr: () => null,
};

/** One-line markdown for the banner's body excerpt. */
export function AnnouncementInlineMarkdown({ content }: { content: string }) {
  return (
    <MarkdownRenderer content={content} componentsOverride={inlineComponents} />
  );
}
