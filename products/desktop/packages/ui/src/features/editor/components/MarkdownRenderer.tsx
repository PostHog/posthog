import { isPostHogCodeDeeplink } from "@posthog/shared";
import { ArtifactRefChip } from "@posthog/ui/features/editor/components/ArtifactRefChip";
import { EvidenceRefChip } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { githubRefChipFor } from "@posthog/ui/features/editor/components/githubRefChipFor";
import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { Divider } from "@posthog/ui/primitives/Divider";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { List, ListItem } from "@posthog/ui/primitives/List";
import { parseArtifactLink } from "@posthog/ui/utils/artifactLinks";
import {
  chartBlockKey,
  isGeneratedChartBlock,
  parseChartBlock,
} from "@posthog/ui/utils/chartBlocks";
import { parseEvidenceLink } from "@posthog/ui/utils/evidenceLinks";
import { remarkObjectTags } from "@posthog/ui/utils/remarkObjectTags";
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
  /**
   * Render PostHog object tags (`<insight/>`, `<hogql/>`…) as live reference
   * chips and chart cards. Off by default because rich objects execute
   * authenticated queries against the viewer's project: only agent-authored
   * surfaces may enable this, never GitHub comments, user messages, or other
   * untrusted content.
   */
  renderObjectTags?: boolean;
  remarkPluginsOverride?: PluggableList;
  componentsOverride?: Partial<Components>;
  rehypePlugins?: PluggableList;
}

// Preprocessor to prevent setext heading interpretation of horizontal rules
// Ensures `---`, `***`, `___` are preceded by a blank line
function preprocessMarkdown(content: string): string {
  return content.replace(/\n([^\n].*)\n(---+|___+|\*\*\*+)\n/g, "\n$1\n\n$2\n");
}

function markdownUrlTransform(value: string, key: string): string {
  // Report summaries reference their charts as `[label](chart:<id>)` links.
  // The scheme survives only on `href` so `![x](chart:y)` can't become an
  // unsanitized image; consumers decide what a chart href renders as.
  if (key === "href" && value.startsWith("chart:")) return value;
  if (isPostHogCodeDeeplink(value)) return value;
  return defaultUrlTransform(value);
}

function objectTagUrlTransform(value: string, key: string): string {
  // Object references (authored as `<kind id="...">` tags, normalized to
  // `evidence:` links by remarkObjectTags) render as inline reference chips
  // with a hover preview; see EvidenceRefChip. Their previews run
  // authenticated queries, so the scheme survives only when the surface
  // opted into object tags.
  if (key === "href" && value.startsWith("evidence:")) return value;
  return markdownUrlTransform(value, key);
}

const HeadingText = ({ children }: { children: React.ReactNode }) => (
  <Text as="p" className="mb-2 text-(--accent-11) text-sm leading-relaxed">
    <strong>{children}</strong>
  </Text>
);

/** A link that leaves the app, with the trailing external-link glyph. */
function ExternalMarkdownLink({
  href,
  children,
}: {
  href: string | undefined;
  children: React.ReactNode;
}) {
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
        // Radix accent vars don't reach portalled surfaces (quill dialogs);
        // without the fallback the glyph draws invisibly, leaving a blank
        // icon-sized gap after the link.
        stroke="var(--accent-11, currentColor)"
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
}

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
    const match = className?.match(/language-([\w-]+)/);
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
  pre: ({ children }) => {
    return <CodeBlock size="1">{children}</CodeBlock>;
  },
  em: ({ children }) => <em>{children}</em>,
  i: ({ children }) => <i>{children}</i>,
  strong: ({ children }) => <strong>{children}</strong>,
  del: ({ children }) => (
    <del className="text-(--gray-9) line-through">{children}</del>
  ),
  a: ({ href, children }) => {
    const evidenceTarget = parseEvidenceLink(href);
    if (evidenceTarget) {
      return (
        <EvidenceRefChip target={evidenceTarget}>{children}</EvidenceRefChip>
      );
    }
    const artifactTarget = parseArtifactLink(href);
    if (artifactTarget && href) {
      return (
        <ArtifactRefChip
          target={artifactTarget}
          href={href}
          fallback={
            <ExternalMarkdownLink href={href}>{children}</ExternalMarkdownLink>
          }
        >
          {children}
        </ArtifactRefChip>
      );
    }
    const githubChip = githubRefChipFor(href, children);
    if (githubChip) return githubChip;
    return <ExternalMarkdownLink href={href}>{children}</ExternalMarkdownLink>;
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

/**
 * Components for surfaces that opted into object tags: `posthog-chart` code
 * nodes generated by remarkObjectTags render as live chart cards. Dispatch
 * requires the plugin's private AST marker, so a hand-authored
 * ```posthog-chart fence stays inert even here.
 */
const objectTagComponents: Components = {
  ...baseComponents,
  code: (props) => {
    const { children, node } = props;
    if (isGeneratedChartBlock(node)) {
      const source = String(children).replace(/\n$/, "");
      const spec = parseChartBlock(source);
      // Malformed or half-streamed JSON renders nothing rather than raw JSON;
      // the block completes (or stays broken) on the next stream snapshot.
      if (!spec) return null;
      return <MessageChartCard spec={spec} blockKey={chartBlockKey(source)} />;
    }
    const BaseCode = baseComponents.code;
    return typeof BaseCode === "function" ? <BaseCode {...props} /> : null;
  },
  pre: (props) => {
    // A chart block renders as a full card, not inside a code block shell.
    if (isGeneratedChartBlock(props.node?.children[0])) {
      return props.children;
    }
    const BasePre = baseComponents.pre;
    return typeof BasePre === "function" ? <BasePre {...props} /> : null;
  },
};

export const defaultRemarkPlugins = [remarkGfm];
const objectTagRemarkPlugins = [...defaultRemarkPlugins, remarkObjectTags];

export const MarkdownRenderer = memo(function MarkdownRenderer({
  content,
  renderObjectTags = false,
  remarkPluginsOverride,
  componentsOverride,
  rehypePlugins,
}: MarkdownRendererProps) {
  const processedContent = useMemo(
    () => preprocessMarkdown(content),
    [content],
  );
  const plugins =
    remarkPluginsOverride ??
    (renderObjectTags ? objectTagRemarkPlugins : defaultRemarkPlugins);
  const base = renderObjectTags ? objectTagComponents : baseComponents;
  const components = useMemo(
    () => (componentsOverride ? { ...base, ...componentsOverride } : base),
    [componentsOverride, base],
  );
  return (
    <ReactMarkdown
      remarkPlugins={plugins}
      rehypePlugins={rehypePlugins}
      components={components}
      urlTransform={
        renderObjectTags ? objectTagUrlTransform : markdownUrlTransform
      }
    >
      {processedContent}
    </ReactMarkdown>
  );
});
