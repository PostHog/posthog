import './LemonMarkdown.scss'

import clsx from 'clsx'
import React, { memo, useMemo } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'

import { CodeSnippet, getLanguage, Language } from 'lib/components/CodeSnippet'
import { RichContentMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'

import { Link } from '../Link'
import remarkMentions from './mention'

/**
 * Link target that places a chart inline in prose, e.g. `[Daily signups](chart:signups-drop)`.
 * A link rather than a bespoke token so the same markdown degrades to a readable label in the
 * renderers that can't draw charts (Slack, the desktop inbox).
 */
export const CHART_REF_PREFIX = 'chart:'

// Matched against the id charset the backend enforces on `chart_id` (see `ChartArtefact` in
// artefact_schemas.py). Anything outside it is not treated as a chart reference at all, so it stays
// subject to the ordinary URL sanitizing rather than riding the `urlTransform` exemption below.
const CHART_REF_TARGET = new RegExp(`^${CHART_REF_PREFIX}([a-z0-9][a-z0-9_-]*)$`)

/** The chart id behind a `chart:` link target, or null when `href` is an ordinary link. */
function chartRefId(href: unknown): string | null {
    return typeof href === 'string' ? (CHART_REF_TARGET.exec(href)?.[1] ?? null) : null
}

/** Link target for a moment in a recording, e.g. `[01:32](t:92000)`, the offset in milliseconds. */
export const TIMESTAMP_REF_PREFIX = 't:'

// Bounded digits, so an overlong target stays an ordinary link and keeps the usual URL sanitizing.
const TIMESTAMP_REF_TARGET = new RegExp(`^${TIMESTAMP_REF_PREFIX}(\\d{1,12})$`)

function timestampRefMs(href: unknown): number | null {
    const digits = typeof href === 'string' ? TIMESTAMP_REF_TARGET.exec(href)?.[1] : undefined
    return digits === undefined ? null : parseInt(digits, 10)
}

/** Whether a paragraph's child node is a chart reference. */
function isChartRefNode(node: any): boolean {
    return node?.tagName === 'a' && chartRefId(node.properties?.href) !== null
}

/** Whether a paragraph's child node carries nothing a reader sees — whitespace or a line break. */
function isBlankNode(node: any): boolean {
    if (node?.type === 'text') {
        return !String(node.value ?? '').trim()
    }
    return node?.tagName === 'br'
}

/** The rendered counterpart of `isBlankNode`: what survives into a side-by-side chart row. */
function isChartRowChild(child: React.ReactNode): boolean {
    return typeof child !== 'string' && (child as React.ReactElement)?.type !== 'br'
}

interface LemonMarkdownContainerProps {
    children: React.ReactNode
    className?: string
}

function LemonMarkdownContainer({ children, className }: LemonMarkdownContainerProps): JSX.Element {
    return <div className={clsx('LemonMarkdown', className)}>{children}</div>
}

export interface LemonMarkdownProps {
    children: string
    /** Whether headings should just be <strong> text. Recommended for item descriptions. */
    lowKeyHeadings?: boolean
    /** Whether to disable the docs sidebar panel behavior and always open links in a new tab */
    disableDocsRedirect?: boolean
    /**
     * Whether to treat images as untrusted. Use for content we don't control (e.g. LLM/agent or
     * externally-sourced output), where auto-loading an image would fire a request to an arbitrary
     * URL — leaking the viewer's IP, acting as a tracking pixel, or probing internal addresses.
     * When set, only images served from PostHog (same-origin or a `posthog.com` host) render inline
     * as <img>; every other image is rendered as a plain click-to-open link instead.
     * `'all'` emits no <img> at all: a same-origin `src` is still a credentialed GET on this host.
     */
    disableImages?: boolean | 'all'
    /** Whether `@member:<id>` / `@role:<id>` stay plain text instead of chips naming a real colleague. */
    disableMentions?: boolean
    /**
     * Whether every link renders as its label rather than an anchor. Preferred over stripping link syntax
     * from the source, which has to out-guess the inline, reference, autolink and image-fallback forms.
     */
    disableLinks?: boolean
    className?: string
    wrapCode?: boolean
    /**
     * If set, block code renders at most this many lines and the rest is cut. The copy button
     * copies the visible lines only. Use where content can carry an unboundedly long code block
     * (e.g. a stack trace) that would otherwise dominate the surrounding UI.
     */
    codeMaxLines?: number
    /** Whether to generate id attributes on heading elements for anchor linking. */
    generateHeadingIds?: boolean
    /**
     * Optional renderer for ` ```mermaid ` code blocks. When omitted, mermaid fences fall back to a
     * plain text CodeSnippet — this is the default so the mermaid library only ships in bundles
     * that opt in (see `LemonMarkdownWithMermaid`).
     */
    renderMermaid?: (code: string) => React.ReactNode
    /**
     * Optional renderer for `chart:<id>` link targets (see `CHART_REF_PREFIX`). `sourceOffset` is
     * where the reference starts in the markdown, so a caller that resolved placement from its own
     * parse can tell one reference to an id from another. Returning null or undefined renders the
     * link's own label as plain text, which is the fallback for an id the caller has no chart for.
     * Omitting this prop renders every chart target as its label — never as a link, since `chart:`
     * is a scheme no browser can follow.
     */
    renderChartRef?: (chartId: string, sourceOffset?: number) => React.ReactNode
    /** Without it, or on a nullish return, a `t:<ms>` target renders as its label. */
    renderTimestampRef?: (timestampMs: number) => React.ReactNode
}

const HEADING_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] as const

/** Generate a URL-safe slug from heading text content. */
export function slugifyHeading(text: string): string {
    return text
        .toLowerCase()
        .replace(/[^\w\s-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '')
}

export function extractTextFromChildren(children: React.ReactNode): string {
    if (typeof children === 'string') {
        return children
    }
    if (typeof children === 'number') {
        return String(children)
    }
    if (Array.isArray(children)) {
        return children.map(extractTextFromChildren).join('')
    }
    if (children && typeof children === 'object' && 'props' in children) {
        return extractTextFromChildren((children as React.ReactElement).props.children)
    }
    return ''
}

const LemonMarkdownRenderer = memo(function LemonMarkdownRenderer({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    disableImages = false,
    disableLinks = false,
    disableMentions = false,
    wrapCode = false,
    codeMaxLines,
    generateHeadingIds = false,
    renderMermaid,
    renderChartRef,
    renderTimestampRef,
}: LemonMarkdownProps): JSX.Element {
    const components = useMemo(
        () => ({
            a: ({ href, children, node }: any): JSX.Element => {
                const timestampMs = timestampRefMs(href)
                if (timestampMs !== null) {
                    return <>{renderTimestampRef?.(timestampMs) ?? children}</>
                }
                const chartId = chartRefId(href)
                if (chartId !== null) {
                    // Falls back to its own label as plain text: for a consumer that can't draw
                    // charts at all, and for an id with no chart behind it (a typo, one deleted since
                    // the summary was written, a repeat of a reference already drawn). Linking it
                    // instead would point the reader at a scheme no browser can follow.
                    return <>{renderChartRef?.(chartId, node?.position?.start?.offset) ?? children}</>
                }
                if (disableLinks) {
                    return <>{children}</>
                }
                return (
                    <Link to={href} target="_blank" targetBlankIcon disableDocsPanel={disableDocsRedirect}>
                        {children}
                    </Link>
                )
            },
            code: ({ className, children, node, ...rest }: any): JSX.Element => {
                const languageMatch = /language-(\w+)/.exec(className || '')
                const isBlock = node?.position?.start?.line !== node?.position?.end?.line || languageMatch
                if (isBlock) {
                    const value = String(children).replace(/\n$/, '')
                    if (renderMermaid && languageMatch && languageMatch[1].toLowerCase() === 'mermaid') {
                        return <>{renderMermaid(value)}</>
                    }
                    const language = languageMatch ? getLanguage(languageMatch[1]) : Language.Text
                    const lines = value.split('\n')
                    const displayedValue =
                        codeMaxLines && lines.length > codeMaxLines ? lines.slice(0, codeMaxLines).join('\n') : value
                    return (
                        <CodeSnippet language={language} wrap={wrapCode} compact>
                            {displayedValue}
                        </CodeSnippet>
                    )
                }
                return (
                    <code className={className} {...rest}>
                        {children}
                    </code>
                )
            },
            pre: ({ children }: any): JSX.Element => {
                // In v9, block code renders as <pre><code>. We handle rendering
                // in the code component, so just pass children through.
                return <>{children}</>
            },
            ...(renderChartRef
                ? {
                      p: ({ children, node }: any): JSX.Element => {
                          const siblings: any[] = node?.children ?? []
                          const chartRefs = siblings.filter(isChartRefNode)
                          // Only a paragraph that holds nothing but references gives up its `<p>`.
                          // One that also carries prose keeps it: those words are a paragraph, and
                          // dropping the tag leaves them as bare text the surrounding typography and
                          // spacing no longer reach. Its reference renders as a label instead —
                          // `resolveChartPlacements` draws that chart after the prose for the same
                          // reason, so the two agree on which paragraphs can hold a chart.
                          if (!siblings.every((n) => isChartRefNode(n) || isBlankNode(n)) || chartRefs.length === 0) {
                              return <p>{children}</p>
                          }
                          // Two or more of them read as "these belong together", so lay them out as a
                          // row that wraps back to a column once the column is too narrow to give
                          // each one a readable width.
                          if (chartRefs.length > 1) {
                              return (
                                  // Top-aligned rather than stretched: charts in a row can be
                                  // different heights, and stretching pads the shorter one with a
                                  // block of empty card.
                                  <div className="flex flex-wrap items-start gap-3 [&>*]:flex-1 [&>*]:basis-64 [&>*]:min-w-0">
                                      {React.Children.toArray(children).filter(isChartRowChild)}
                                  </div>
                              )
                          }
                          // A rendered chart is block-level, and a paragraph containing one would put a
                          // <div> inside a <p>, which the browser closes early and reparents. Drop the
                          // <p> for those paragraphs; the chart brings its own block spacing.
                          return <>{children}</>
                      },
                  }
                : {}),
            span: ({ className, ...props }: any): JSX.Element => {
                if (className === 'ph-mention') {
                    return <RichContentMention id={Number(props['data-mention-id'])} />
                }
                return <span className={className} {...props} />
            },
            ...(disableImages
                ? {
                      img: ({ src, alt }: any): JSX.Element => {
                          if (disableImages !== 'all' && isTrustedPostHogUrl(src)) {
                              return <img src={src} alt={alt} loading="lazy" />
                          }
                          // The click-to-open fallback is an anchor, so it answers to `disableLinks` too.
                          return disableLinks ? (
                              <>{alt || src}</>
                          ) : (
                              <Link to={src} target="_blank" targetBlankIcon disableDocsPanel>
                                  {alt || src}
                              </Link>
                          )
                      },
                  }
                : {}),
            li: ({ children, node }: any): JSX.Element => {
                const isTaskItem = node?.properties?.className?.includes('task-list-item')
                if (isTaskItem) {
                    // remark-gfm v4 renders task list items with an <input> checkbox child.
                    // We replace it with our LemonCheckbox.
                    const inputChild = node?.children?.find(
                        (child: any) => child.tagName === 'input' && child.properties?.type === 'checkbox'
                    )
                    const checked = inputChild?.properties?.checked ?? false
                    // Filter out the default checkbox input from rendered children
                    const filteredChildren = React.Children.toArray(children).filter(
                        (child: any) => !(child?.type === 'input' && child?.props?.type === 'checkbox')
                    )
                    return (
                        <li className="LemonMarkdown__task">
                            <LemonCheckbox checked={checked} disabledReason="Read-only for display" size="small" />
                            <span className="LemonMarkdown__task-content">{filteredChildren}</span>
                        </li>
                    )
                }
                return <li>{children}</li>
            },
            ...(lowKeyHeadings
                ? Object.fromEntries(
                      HEADING_TAGS.map((tag) => [
                          tag,
                          ({ children }: any): JSX.Element => (
                              <strong className="LemonMarkdown__low-key-heading">{children}</strong>
                          ),
                      ])
                  )
                : generateHeadingIds
                  ? Object.fromEntries(
                        HEADING_TAGS.map((tag) => [
                            tag,
                            ({ children }: any): JSX.Element => {
                                const id = slugifyHeading(extractTextFromChildren(children))
                                return React.createElement(tag, { id }, children)
                            },
                        ])
                    )
                  : {}),
        }),
        [
            disableDocsRedirect,
            disableImages,
            disableLinks,
            lowKeyHeadings,
            wrapCode,
            codeMaxLines,
            generateHeadingIds,
            renderMermaid,
            renderChartRef,
            renderTimestampRef,
        ]
    )

    // The default sanitizer strips both schemes, so let them through, on `href` only.
    const urlTransform = useMemo(
        () =>
            (url: string, key: string): string =>
                key === 'href' && (chartRefId(url) !== null || timestampRefMs(url) !== null)
                    ? url
                    : defaultUrlTransform(url),
        []
    )

    // remark-breaks: a single newline becomes a line break, so prose authored without the arcane
    // two-trailing-spaces hard-break rule (e.g. agent-written report summaries) renders with the
    // line breaks the author intended.
    const remarkPlugins = useMemo(
        () => (disableMentions ? [remarkGfm, remarkBreaks] : [remarkGfm, remarkBreaks, remarkMentions]),
        [disableMentions]
    )

    return (
        /* eslint-disable-next-line react/forbid-elements */
        <ReactMarkdown components={components} remarkPlugins={remarkPlugins} urlTransform={urlTransform} skipHtml>
            {children}
        </ReactMarkdown>
    )
})

/** Beautifully rendered Markdown. */
function LemonMarkdownComponent({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    disableImages = false,
    disableLinks = false,
    disableMentions = false,
    wrapCode = false,
    codeMaxLines,
    generateHeadingIds = false,
    renderMermaid,
    renderChartRef,
    renderTimestampRef,
    className,
}: LemonMarkdownProps): JSX.Element {
    return (
        <LemonMarkdownContainer className={className}>
            <LemonMarkdownRenderer
                lowKeyHeadings={lowKeyHeadings}
                disableDocsRedirect={disableDocsRedirect}
                disableImages={disableImages}
                disableLinks={disableLinks}
                disableMentions={disableMentions}
                wrapCode={wrapCode}
                codeMaxLines={codeMaxLines}
                generateHeadingIds={generateHeadingIds}
                renderMermaid={renderMermaid}
                renderChartRef={renderChartRef}
                renderTimestampRef={renderTimestampRef}
            >
                {children}
            </LemonMarkdownRenderer>
        </LemonMarkdownContainer>
    )
}

export const LemonMarkdown = Object.assign(LemonMarkdownComponent, {
    Container: LemonMarkdownContainer,
    Renderer: LemonMarkdownRenderer,
})
