import './LemonMarkdown.scss'

import clsx from 'clsx'
import React, { memo, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { IconX } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { RichContentMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { RichContentNodeType } from 'lib/components/RichContentEditor/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { Link } from '../Link'
import remarkMentions from './mention'

function ImageWithLightbox({ src, alt }: { src: string; alt?: string }): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [isLoading, setIsLoading] = useState(true)
    const [hasError, setHasError] = useState(false)

    // Reset state when src changes (e.g., if component is reused with different image)
    React.useEffect(() => {
        setIsLoading(true)
        setHasError(false)
    }, [src])

    if (hasError) {
        return (
            <span className="LemonMarkdown__image-error text-muted-alt text-xs italic">
                Failed to load image{alt ? `: ${alt}` : ''}
            </span>
        )
    }

    return (
        <>
            <span className="LemonMarkdown__image-wrapper">
                {isLoading && <LemonSkeleton className="LemonMarkdown__image-skeleton" />}
                <img
                    src={src}
                    alt={alt || 'Image'}
                    className={clsx('LemonMarkdown__image', isLoading && 'invisible')}
                    onClick={() => setIsOpen(true)}
                    onLoad={() => setIsLoading(false)}
                    onError={() => {
                        setIsLoading(false)
                        setHasError(true)
                    }}
                    loading="lazy"
                />
            </span>
            <LemonModal isOpen={isOpen} onClose={() => setIsOpen(false)} simple>
                <div className="relative">
                    <LemonButton
                        icon={<IconX />}
                        size="small"
                        onClick={() => setIsOpen(false)}
                        className="absolute top-2 right-2 z-10 bg-surface-primary"
                    />
                    <img src={src} alt={alt || 'Image'} className="max-w-[90vw] max-h-[90vh] rounded" />
                </div>
            </LemonModal>
        </>
    )
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
    className?: string
    wrapCode?: boolean
}

const LemonMarkdownRenderer = memo(function LemonMarkdownRenderer({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
}: LemonMarkdownProps): JSX.Element {
    const renderers = useMemo<{ [nodeType: string]: React.ElementType }>(
        () => ({
            link: ({ href, children }: any): JSX.Element => (
                <Link to={href} target="_blank" targetBlankIcon disableDocsPanel={disableDocsRedirect}>
                    {children}
                </Link>
            ),
            code: ({ language, value }: any): JSX.Element => (
                <CodeSnippet language={language || Language.Text} wrap={wrapCode} compact>
                    {value}
                </CodeSnippet>
            ),
            [RichContentNodeType.Mention]: ({ id }): JSX.Element => <RichContentMention id={id} />,
            image: ({ src, alt }: { src: string; alt?: string }): JSX.Element => (
                <ImageWithLightbox src={src} alt={alt} />
            ),
            listItem: ({ checked, children }: any): JSX.Element => {
                // Handle task list items with LemonCheckbox
                if (checked != null) {
                    return (
                        <li className="LemonMarkdown__task">
                            <LemonCheckbox checked={checked} disabledReason="Read-only for display" size="small" />
                            <span className="LemonMarkdown__task-content">{children}</span>
                        </li>
                    )
                }
                // Regular list item
                return <li>{children}</li>
            },
            ...(lowKeyHeadings
                ? {
                      heading: 'strong',
                  }
                : {}),
        }),
        [disableDocsRedirect, lowKeyHeadings, wrapCode]
    )

    return (
        /* eslint-disable-next-line react/forbid-elements */
        <ReactMarkdown
            renderers={renderers}
            disallowedTypes={['html']} // Don't want to deal with the security considerations of HTML
            plugins={[remarkGfm, remarkMentions]}
        >
            {children}
        </ReactMarkdown>
    )
})

/** Beautifully rendered Markdown. */
function LemonMarkdownComponent({
    children,
    lowKeyHeadings = false,
    disableDocsRedirect = false,
    wrapCode = false,
    className,
}: LemonMarkdownProps): JSX.Element {
    return (
        <LemonMarkdownContainer className={className}>
            <LemonMarkdownRenderer
                lowKeyHeadings={lowKeyHeadings}
                disableDocsRedirect={disableDocsRedirect}
                wrapCode={wrapCode}
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
