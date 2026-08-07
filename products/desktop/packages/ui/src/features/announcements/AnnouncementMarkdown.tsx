import { isPostHogCodeDeeplink } from "@posthog/shared";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useMemo } from "react";
import type { Components } from "react-markdown";
import { useOpenAnnouncementCta } from "./announcementCta";

type OpenCta = (url: string) => "deeplink" | "external";

// Announcement bodies render inside a quill dialog, where the app's default
// markdown link (Radix accent color plus an external-link glyph) has no theme
// vars — the glyph draws invisibly and leaves a blank gap. Plain anchors let
// quill's own dialog-description link styling take over, and clicks route
// through the announcement CTA opener so https and posthog-code:// both work.
function buildComponents(openCta: OpenCta): Partial<Components> {
  return {
    a: ({ href, children }) => {
      // Body links follow the same contract as CTAs: https or a posthog-code
      // deep link. Anything else renders as plain text.
      if (
        !href ||
        !(href.startsWith("https://") || isPostHogCodeDeeplink(href))
      ) {
        return <>{children}</>;
      }
      return (
        <a
          href={href}
          className="underline underline-offset-2"
          onClick={(event) => {
            event.preventDefault();
            openCta(href);
          }}
        >
          {children}
        </a>
      );
    },
  };
}

export function AnnouncementMarkdown({ content }: { content: string }) {
  const openCta = useOpenAnnouncementCta();
  const components = useMemo(() => buildComponents(openCta), [openCta]);
  return <MarkdownRenderer content={content} componentsOverride={components} />;
}

// Block elements collapse to their inline content so the result fits a
// single truncating line.
function buildInlineComponents(openCta: OpenCta): Partial<Components> {
  return {
    ...buildComponents(openCta),
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
}

/** One-line markdown for the banner's body excerpt. */
export function AnnouncementInlineMarkdown({ content }: { content: string }) {
  const openCta = useOpenAnnouncementCta();
  const components = useMemo(() => buildInlineComponents(openCta), [openCta]);
  return <MarkdownRenderer content={content} componentsOverride={components} />;
}
