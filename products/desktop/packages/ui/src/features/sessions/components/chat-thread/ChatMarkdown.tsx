import { Check, Copy } from "@phosphor-icons/react";
import {
  Heading,
  Separator,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Text,
} from "@posthog/quill";
import { useWorkspaceFileAsBase64 } from "@posthog/ui/features/code-editor/hooks/useFileContent";
import { ArtifactRefChip } from "@posthog/ui/features/editor/components/ArtifactRefChip";
import { EvidenceRefChip } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { githubRefChipFor } from "@posthog/ui/features/editor/components/githubRefChipFor";
import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import {
  markOpenLinkDestination,
  parseOpenFence,
  splitMarkdownBlocks,
} from "@posthog/ui/features/editor/components/splitMarkdownBlocks";
import {
  BareFileLink,
  hasDirectoryPath,
  InlineFileLink,
  looksLikeBareFilename,
} from "@posthog/ui/features/sessions/components/session-update/fileLinkChips";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { useCwd } from "@posthog/ui/features/sidebar/useCwd";
import { useThrottledValue } from "@posthog/ui/hooks/useThrottledValue";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { MermaidDiagram } from "@posthog/ui/primitives/MermaidDiagram";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useCopy } from "@posthog/ui/primitives/useCopy";
import { parseArtifactLink } from "@posthog/ui/utils/artifactLinks";
import {
  CHART_BLOCK_MARKER,
  chartBlockKey,
  isGeneratedChartBlock,
  parseChartBlock,
} from "@posthog/ui/utils/chartBlocks";
import { parseEvidenceLink } from "@posthog/ui/utils/evidenceLinks";
import { MERMAID_LANGUAGE } from "@posthog/ui/utils/mermaidBlocks";
import { remarkObjectTags } from "@posthog/ui/utils/remarkObjectTags";
import { IconButton } from "@radix-ui/themes";
import { memo, type ReactNode, useEffect, useMemo, useRef } from "react";
import Markdown, { type Components, defaultUrlTransform } from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";

const PENDING_LINK_DESTINATION = "#posthog-streaming-link";

const LOCAL_IMAGE_MIME_TYPES: Record<string, string> = {
  avif: "image/avif",
  gif: "image/gif",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
};

function normalizeLocalPath(value: string): string | null {
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  const normalized = decoded.replaceAll("\\\\", "/");
  const prefix = normalized.match(/^(?:[A-Za-z]:|\/)/)?.[0];
  if (!prefix) return null;

  const parts: string[] = [];
  for (const part of normalized.slice(prefix.length).split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.pop()) return null;
    } else {
      parts.push(part);
    }
  }
  return `${prefix}${prefix === "/" ? "" : "/"}${parts.join("/")}`;
}

export function resolveLocalImage(
  source: string | undefined,
  cwd: string | undefined,
): { path: string; mimeType: string } | null {
  if (!source || !cwd) return null;
  if (
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(source) &&
    !/^[A-Za-z]:[\\/]/.test(source)
  ) {
    return null;
  }
  const normalizedCwd = normalizeLocalPath(cwd);
  if (!normalizedCwd) return null;
  const sourceWithRoot = /^(?:[A-Za-z]:[\\/]|\/)/.test(source)
    ? source
    : `${normalizedCwd}/${source}`;
  const path = normalizeLocalPath(sourceWithRoot);
  if (
    !path ||
    (path !== normalizedCwd && !path.startsWith(`${normalizedCwd}/`))
  ) {
    return null;
  }
  const extension = path.match(/\.([A-Za-z0-9]+)$/)?.[1]?.toLowerCase();
  const mimeType = extension ? LOCAL_IMAGE_MIME_TYPES[extension] : undefined;
  return mimeType ? { path, mimeType } : null;
}

function LocalMarkdownImage({
  src,
  alt,
}: {
  src: string | undefined;
  alt: string | undefined;
}) {
  const taskId = useSessionTaskId();
  const cwd = useCwd(taskId ?? "");
  const localImage = resolveLocalImage(src, cwd);
  const image = useWorkspaceFileAsBase64(
    cwd ?? "",
    localImage?.path ?? "",
    Boolean(taskId && localImage),
  );

  if (!localImage) {
    return (
      <Text className="text-muted-foreground text-sm">
        Remote image blocked{alt ? `: ${alt}` : ""}
      </Text>
    );
  }
  if (image.isPending) {
    return <Spinner size="sm" aria-label={alt || "Loading image"} />;
  }
  if (!image.data) {
    return (
      <Text className="text-muted-foreground text-sm">
        Failed to load image{alt ? `: ${alt}` : ""}
      </Text>
    );
  }
  return (
    <img
      src={image.data}
      alt={alt ?? ""}
      className="max-h-[32rem] max-w-full rounded-md border border-border object-contain"
    />
  );
}

function ChatCodeBlock({
  code,
  children,
}: {
  code: string;
  children: ReactNode;
}) {
  const { copied, copy } = useCopy();

  return (
    <div className="group relative">
      <pre className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 pr-10 text-sm leading-[1.5]">
        {children}
      </pre>
      <IconButton
        size="1"
        variant="ghost"
        color={copied ? "green" : "gray"}
        onClick={() => copy(code)}
        className="absolute top-1 right-1 cursor-pointer opacity-0 transition-opacity group-hover:opacity-100"
        aria-label="Copy code"
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </IconButton>
    </div>
  );
}

/**
 * The chat thread's own markdown renderer — intentionally separate from the app-wide
 * `MarkdownRenderer` (which carries PostHog deeplink handling, Radix Text wrappers, and other
 * product baggage). This one is a thin, generic react-markdown setup for chat bubble content:
 * GFM + sanitized HTML, minimal prose styling. Restyle the element map below per product.
 */
const components: Components = {
  p: ({ children }) => (
    <Text className="text-sm leading-[1.5]">{children}</Text>
  ),
  a: ({ children, href }) => {
    if (href === PENDING_LINK_DESTINATION) {
      return (
        <output
          className="inline-flex items-center gap-1 text-primary underline underline-offset-2"
          aria-label="Link loading"
        >
          {children}
          <Spinner size="sm" aria-hidden="true" />
        </output>
      );
    }
    const evidenceTarget = parseEvidenceLink(href);
    if (evidenceTarget) {
      return (
        <EvidenceRefChip target={evidenceTarget}>{children}</EvidenceRefChip>
      );
    }
    const githubChip = githubRefChipFor(href, children);
    if (githubChip) return githubChip;
    const link = (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-primary underline underline-offset-2"
      >
        {children}
      </a>
    );
    const artifactTarget = parseArtifactLink(href);
    if (!artifactTarget || !href) return link;
    return (
      <ArtifactRefChip target={artifactTarget} href={href} fallback={link}>
        {children}
      </ArtifactRefChip>
    );
  },
  img: ({ alt, src }) => <LocalMarkdownImage src={src} alt={alt} />,
  ul: ({ children }) => (
    <ul className="list-disc space-y-0.5 ps-4">{children}</ul>
  ),
  ol: ({ children, start }) => (
    <ol start={start} className="list-decimal space-y-0.5 ps-8">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="text-sm">{children}</li>,
  code: ({ className, children, node }) => {
    const text = String(children).replace(/\n$/, "");
    const match = /language-([\w-]+)/.exec(className ?? "");
    // Block-display object tags normalize to posthog-chart code nodes (see
    // remarkObjectTags); they render as chart cards, not code. Dispatch
    // requires the plugin's private AST marker so a hand-authored fence stays
    // inert. Malformed or half-streamed specs render nothing rather than raw
    // JSON.
    if (isGeneratedChartBlock(node)) {
      const spec = parseChartBlock(text);
      if (!spec) return null;
      return <MessageChartCard spec={spec} blockKey={chartBlockKey(text)} />;
    }
    if (match?.[1].toLowerCase() === MERMAID_LANGUAGE) {
      return <MermaidDiagram code={text} />;
    }
    // Fenced blocks (carry a language, or span multiple lines) render as a boxed, copyable
    // block; short inline spans stay inline. `pre` below is a passthrough so the box lives here,
    // where the raw code string is in hand.
    if (match || text.includes("\n")) {
      return (
        <ChatCodeBlock code={text}>
          {match ? (
            <HighlightedCode
              code={text}
              language={match[1]}
              className="text-xs"
            />
          ) : (
            <code className="font-mono text-xs">{text}</code>
          )}
        </ChatCodeBlock>
      );
    }
    const fallback = (
      <code className="rounded rounded-sm border border-border bg-muted/50 px-1 font-mono text-xs">
        {children}
      </code>
    );
    if (hasDirectoryPath(text)) {
      return <InlineFileLink text={text} />;
    }
    if (looksLikeBareFilename(text)) {
      return <BareFileLink text={text} fallback={fallback} />;
    }
    return fallback;
  },
  pre: ({ children }) => <>{children}</>,
  h1: ({ children }) => (
    <Heading size="xl" className="font-bold">
      {children}
    </Heading>
  ),
  h2: ({ children }) => (
    <Heading size="lg" className="font-bold">
      {children}
    </Heading>
  ),
  h3: ({ children }) => (
    <Heading size="base" className="font-bold">
      {children}
    </Heading>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-(--gray-6) border-s-2 ps-3 text-(--gray-11)">
      {children}
    </blockquote>
  ),
  hr: () => <Separator />,
  table: ({ children }) => (
    <Table size="sm" className="rounded-md border border-border">
      {children}
    </Table>
  ),
  thead: ({ children }) => <TableHeader>{children}</TableHeader>,
  th: ({ children }) => <TableHead>{children}</TableHead>,
  tbody: ({ children }) => <TableBody>{children}</TableBody>,
  tr: ({ children }) => <TableRow>{children}</TableRow>,
  td: ({ children }) => <TableCell>{children}</TableCell>,
};

// The internal `evidence:` hrefs never reach the DOM (the `a` component
// renders them as chips), but they must survive react-markdown's default
// transform, which empties unknown protocols.
function chatUrlTransform(value: string, key: string): string {
  if (key === "href" && value.startsWith("evidence:")) return value;
  return defaultUrlTransform(value);
}

const remarkPlugins: PluggableList = [remarkGfm];
const objectTagRemarkPlugins: PluggableList = [remarkGfm, remarkObjectTags];
// The default sanitize schema, plus what remarkObjectTags emits: the internal
// `evidence:` reference links (they never reach the DOM as hrefs; the `a`
// component renders them as chips) and the private marker on generated chart
// code nodes (unforgeable from text, since raw HTML is never parsed here).
const rehypePlugins: PluggableList = [
  [
    rehypeSanitize,
    {
      ...defaultSchema,
      attributes: {
        ...defaultSchema.attributes,
        code: [...(defaultSchema.attributes?.code ?? []), CHART_BLOCK_MARKER],
      },
      protocols: {
        ...defaultSchema.protocols,
        href: [...(defaultSchema.protocols?.href ?? []), "evidence"],
      },
    },
  ],
];

interface ChatMarkdownProps {
  content: string;
  /** See MarkdownRenderer: only trusted agent-authored surfaces may enable
   *  object tags, because they execute authenticated queries. */
  renderObjectTags?: boolean;
}

export const ChatMarkdown = memo(function ChatMarkdown({
  content,
  renderObjectTags = false,
}: ChatMarkdownProps) {
  return (
    <div className="flex flex-col gap-3 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <Markdown
        remarkPlugins={
          renderObjectTags ? objectTagRemarkPlugins : remarkPlugins
        }
        rehypePlugins={rehypePlugins}
        urlTransform={renderObjectTags ? chatUrlTransform : defaultUrlTransform}
        components={components}
      >
        {content}
      </Markdown>
    </div>
  );
});

const LARGE_TAIL_CHARS = 2_000;
const TAIL_CHARS_PER_INTERVAL_MS = 100;
const MIN_TAIL_PARSE_INTERVAL_MS = 100;
const MAX_TAIL_PARSE_INTERVAL_MS = 500;

function tailParseInterval(tailLength: number): number {
  return Math.min(
    MAX_TAIL_PARSE_INTERVAL_MS,
    Math.max(
      MIN_TAIL_PARSE_INTERVAL_MS,
      tailLength / TAIL_CHARS_PER_INTERVAL_MS,
    ),
  );
}

/**
 * Streaming variant of {@link ChatMarkdown}: splits the message into top-level blocks so completed
 * blocks keep a stable string and their memoized parse is reused — each streamed frame re-parses
 * only the growing tail block, O(last block) instead of O(message).
 *
 * While the tail sits inside an unterminated code fence it renders as plain monospace in the same
 * `pre` box the finished block will use — no per-frame Shiki highlight, no layout shift when the
 * fence closes. Completed messages should render through {@link ChatMarkdown} directly for a
 * single, fully-correct parse.
 */
export const ChatStreamingMarkdown = memo(function ChatStreamingMarkdown({
  content,
  renderObjectTags,
}: ChatMarkdownProps) {
  // The throttle has to be sized before the split that measures the tail, so it reads the
  // last rendered tail instead: the interval lags by at most one interval.
  const tailLengthRef = useRef(0);
  const renderedContent = useThrottledValue(
    content,
    tailParseInterval(tailLengthRef.current),
    tailLengthRef.current > LARGE_TAIL_CHARS,
  );
  const blocks = useMemo(
    () => splitMarkdownBlocks(renderedContent),
    [renderedContent],
  );
  const lastIndex = blocks.length - 1;
  const tailBlock = blocks[lastIndex];
  useEffect(() => {
    tailLengthRef.current = tailBlock.length;
  }, [tailBlock]);
  const tail = useMemo(
    () => ({
      openFence: parseOpenFence(tailBlock),
      linked: markOpenLinkDestination(tailBlock, PENDING_LINK_DESTINATION),
    }),
    [tailBlock],
  );

  return (
    <div className="flex flex-col gap-3 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      {blocks.map((block, index) => {
        const key = `b${index}`;
        if (index !== lastIndex) {
          return (
            <ChatMarkdown
              key={key}
              content={block}
              renderObjectTags={renderObjectTags}
            />
          );
        }
        if (tail.openFence) {
          return (
            <div key={key} className="flex flex-col gap-3">
              {tail.openFence.before.trim() ? (
                <ChatMarkdown
                  content={tail.openFence.before}
                  renderObjectTags={renderObjectTags}
                />
              ) : null}
              <ChatCodeBlock code={tail.openFence.code}>
                <code className="font-mono text-xs">{tail.openFence.code}</code>
              </ChatCodeBlock>
            </div>
          );
        }
        return (
          <ChatMarkdown
            key={key}
            content={tail.linked}
            renderObjectTags={renderObjectTags}
          />
        );
      })}
    </div>
  );
});
