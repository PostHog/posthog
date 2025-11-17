import clsx from 'clsx'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronRight, IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface TemplateLinkSectionProps {
    templateLink: string
    onShortenLink?: () => void
    showShortenButton?: boolean
    heading?: string
    tooltip?: string
    piiWarning?: string
    copyButtonLabel?: string
    collapsible?: boolean
    defaultExpanded?: boolean
}

export function TemplateLinkSection({
    templateLink,
    onShortenLink,
    showShortenButton = false,
    heading,
    tooltip,
    piiWarning = 'Be aware that you may be sharing sensitive data if contained in your event, property names or filters.',
    collapsible = false,
    defaultExpanded = true,
    copyButtonLabel,
}: TemplateLinkSectionProps): JSX.Element {
    const [copied, setCopied] = useState(false)
    const [isExpanded, setIsExpanded] = useState(collapsible ? defaultExpanded : true)

    const isMultiline = templateLink.includes('\n')

    const handleCopyLink = async (): Promise<void> => {
        try {
            await copyToClipboard(templateLink)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        } catch (e) {
            posthog.captureException(new Error('unexpected template link clipboard error: ' + (e as Error).message))
        }
    }

    const headingIcon =
        tooltip && tooltip.trim() ? (
            <Tooltip title={tooltip}>
                <IconInfo />
            </Tooltip>
        ) : undefined

    const contentVisible = collapsible ? isExpanded : true

    return (
        <div className="deprecated-space-y-2">
            {typeof heading === 'string' &&
                heading &&
                (collapsible ? (
                    <button
                        type="button"
                        className="flex w-full items-center gap-2 rounded bg-transparent p-0 text-left cursor-pointer"
                        onClick={() => setIsExpanded((value) => !value)}
                        aria-expanded={isExpanded}
                    >
                        <IconChevronRight
                            className={clsx('shrink-0 text-lg text-secondary transition-transform', {
                                'rotate-90': isExpanded,
                            })}
                        />
                        {headingIcon ? (
                            <span className="flex items-center gap-2">
                                {headingIcon}
                                <b>{heading}</b>
                            </span>
                        ) : (
                            <b>{heading}</b>
                        )}
                    </button>
                ) : (
                    <TitleWithIcon icon={headingIcon ?? <span />}>
                        <b>{heading}</b>
                    </TitleWithIcon>
                ))}
            {contentVisible && (
                <>
                    {piiWarning && <p className="text-muted mb-1">{piiWarning}</p>}
                    <div className="flex items-start gap-2">
                        <div className="flex-1">
                            {isMultiline ? (
                                <CodeSnippet language={Language.JavaScript} maxLinesWithoutExpansion={3} wrap compact>
                                    {templateLink}
                                </CodeSnippet>
                            ) : (
                                <input
                                    type="text"
                                    value={templateLink}
                                    readOnly
                                    className="w-full px-3 py-2 text-sm border rounded bg-bg-light"
                                    onClick={(e) => (e.target as HTMLInputElement).select()}
                                />
                            )}
                        </div>
                        {copyButtonLabel ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    void handleCopyLink()
                                }}
                                icon={<IconLink />}
                            >
                                {copied ? 'Copied!' : copyButtonLabel}
                            </LemonButton>
                        ) : null}
                    </div>

                    {showShortenButton && (
                        <>
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <LemonButton type="secondary" onClick={onShortenLink} disabled={!onShortenLink}>
                                            Shorten URL
                                        </LemonButton>
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    )
}
