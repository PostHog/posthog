import { isPostHogCodeDeeplink } from "@posthog/shared";
import { GithubRefChip } from "@posthog/ui/features/editor/components/GithubRefChip";
import { parseGithubIssueUrl } from "@posthog/ui/features/message-editor/githubIssueUrl";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { Divider } from "@posthog/ui/primitives/Divider";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { List, ListItem } from "@posthog/ui/primitives/List";
import { handleShareLinkClick } from "@posthog/ui/utils/shareLinks";
import { Blockquote, Checkbox, Code, Kbd, Text } from "@radix-ui/themes";
import { memo, useMemo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";
import { openExternalUrl } from "../../../shell/openExternal";

interface MarkdownRendererProps {
  content: string;
  remarkPluginsOverride?: PluggableList;
  componentsOverride?: Partial<Components>;
  rehypePlugins?: PluggableList;
}

// Preprocessor to prevent setext heading interpretation of horizontal rules
// Ensures `---`, `***`, `___` are preceded by a blank line
function preprocessMarkdown(content: string): string {
  return content.replace(/\n([^\n].*)\n(---+|___+|\*\*\*+)\n/g, "\n$1\n\n$2\n");
}

function markdownUrlTransform(value: string): string {
  if (isPostHogCodeDeeplink(value)) return value;
  return defaultUrlTransform(value);
}

const HeadingText = ({ children }: { children: React.ReactNode }) => (
  <Text as="p" className="mb-2 text-(--accent-11) text-sm leading-relaxed">
    <strong>{children}</strong>
  </Text>
);

export const baseComponents: Components = {
  h1: ({ children }) => <HeadingText>{children}</HeadingText>,
  h2: ({ children }) => <HeadingText>{children}</HeadingText>,
  h3: ({ children }) => <HeadingText>{children}</HeadingText>,
  h4: ({ children }) => <HeadingText>{children}</HeadingText>,
  h5: ({ children }) => <HeadingText>{children}</HeadingText>,
  h6: ({ children }) => <HeadingText>{children}</HeadingText>,
  p: ({ children }) => (
    <Text as="p" className="mb-2">
      {children}
    </Text>
  ),
  blockquote: ({ children }) => (
    <Blockquote size="1" mb="2" style={{ borderColor: "var(--accent-6)" }}>
      {children}
    </Blockquote>
  ),
  code: ({ children, className }) => {
    const match = className?.match(/language-(\w+)/);
    if (!match) {
      return <Code variant="ghost">{children}</Code>;
    }
    return (
      <HighlightedCode
        code={String(children).replace(/\n$/, "")}
        language={match[1]}
      />
    );
  },
  pre: ({ children }) => <CodeBlock size="1">{children}</CodeBlock>,
  em: ({ children }) => <em>{children}</em>,
  i: ({ children }) => <i>{children}</i>,
  strong: ({ children }) => <strong>{children}</strong>,
  del: ({ children }) => (
    <del className="text-(--gray-9) line-through">{children}</del>
  ),
  a: ({ href, children }) => {
    const githubRef = href ? parseGithubIssueUrl(href) : null;
    if (githubRef) {
      const isAutoLink = typeof children === "string" && children === href;
      const label = isAutoLink
        ? `${githubRef.owner}/${githubRef.repo}#${githubRef.number}`
        : children;
      return (
        <GithubRefChip href={githubRef.normalizedUrl} kind={githubRef.kind}>
          {label}
        </GithubRefChip>
      );
    }
    const isDeeplink = isPostHogCodeDeeplink(href);
    return (
      <a
        href={href}
        onClick={(event) => {
          if (handleShareLinkClick(href, event)) return;
          if (!isDeeplink || !href) return;
          event.preventDefault();
          openExternalUrl(href);
        }}
        target="_blank"
        rel="noopener noreferrer"
        className="markdown-link inline-flex items-center gap-[2px]"
      >
        {children}
        <svg
          width="10"
          height="10"
          viewBox="0 0 12 12"
          fill="none"
          stroke="var(--accent-11)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-label="external link icon"
          role="img"
          className="ml-1 shrink-0"
        >
          <path d="M4.5 1.5H2.25C1.836 1.5 1.5 1.836 1.5 2.25V9.75C1.5 10.164 1.836 10.5 2.25 10.5H9.75C10.164 10.5 10.5 10.164 10.5 9.75V7.5" />
          <path d="M7.5 1.5H10.5V4.5" />
          <path d="M5.25 6.75L10.5 1.5" />
        </svg>
      </a>
    );
  },
  kbd: ({ children }) => <Kbd>{children}</Kbd>,
  ul: ({ children }) => (
    <List as="ul" size="1">
      {children}
    </List>
  ),
  ol: ({ children }) => (
    <List as="ol" size="1">
      {children}
    </List>
  ),
  li: ({ children }) => <ListItem size="1">{children}</ListItem>,
  hr: () => <Divider size="3" />,
  // Task list checkbox
  input: ({ type, checked }) => {
    if (type === "checkbox") {
      return (
        <Checkbox
          checked={checked}
          size="1"
          style={{ verticalAlign: "middle" }}
          className="mr-1"
        />
      );
    }
    return <input type={type} />;
  },
  // Table components - plain HTML for size control
  table: ({ children }) => <table className="mb-3">{children}</table>,
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-gray-6 border-b">{children}</tr>,
  th: ({ children, style }) => (
    <th className="px-2 py-1 text-left text-gray-11" style={style}>
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td className="px-2 py-1 text-gray-12" style={style}>
      {children}
    </td>
  ),
};

export const defaultRemarkPlugins = [remarkGfm];

export const MarkdownRenderer = memo(function MarkdownRenderer({
  content,
  remarkPluginsOverride,
  componentsOverride,
  rehypePlugins,
}: MarkdownRendererProps) {
  const processedContent = useMemo(
    () => preprocessMarkdown(content),
    [content],
  );
  const plugins = remarkPluginsOverride ?? defaultRemarkPlugins;
  const components = useMemo(
    () =>
      componentsOverride
        ? { ...baseComponents, ...componentsOverride }
        : baseComponents,
    [componentsOverride],
  );
  return (
    <ReactMarkdown
      remarkPlugins={plugins}
      rehypePlugins={rehypePlugins}
      components={components}
      urlTransform={markdownUrlTransform}
    >
      {processedContent}
    </ReactMarkdown>
  );
});
