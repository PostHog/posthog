import './CommandBlock.scss'

import { useState } from 'react'

import { IconCopy, IconTerminal } from '@posthog/icons'

import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

type Size = 'sm' | 'md'
type Decoration = 'plain' | 'rainbow'

const SIZE_STYLES: Record<Size, { padding: string; font: string; icon: string }> = {
    sm: { padding: 'px-2.5 py-1.5', font: 'text-xs', icon: 'size-3.5' },
    md: { padding: 'px-4 py-3', font: 'text-sm', icon: 'size-4' },
}

interface CommandBlockProps {
    command: string
    /** Label passed to the copy-to-clipboard toast (e.g. "MCP install command"). */
    copyLabel: string
    ariaLabel: string
    className?: string
    size?: Size
    /** Visual treatment of the command text:
     *  - `plain` (default): the default code color, no animation.
     *  - `rainbow`: animated brand gradient — reserved for AI/MCP-flavored commands.
     */
    decoration?: Decoration
    /** Fired after each copy click, with a monotonically increasing key. Lets callers
     *  trigger their own keyed remount animations (e.g. the wizard hedgehog cast). */
    onCopy?: (copyKey: number) => void
    /** Skip the "Copied … to clipboard" toast. Set when this block lives inside another
     *  long-lived toast that would otherwise get pushed around by the success info toast. */
    silentCopy?: boolean
}

export function CommandBlock({
    command,
    copyLabel,
    ariaLabel,
    className,
    size = 'md',
    decoration = 'plain',
    onCopy,
    silentCopy = false,
}: CommandBlockProps): JSX.Element {
    const [copyKey, setCopyKey] = useState(0)
    const sizeStyle = SIZE_STYLES[size]
    const isStorybook = inStorybook() || inStorybookTestRunner()

    const handleCopy = (): void => {
        void copyToClipboard(command, copyLabel, { silent: silentCopy })
        const next = copyKey + 1
        setCopyKey(next)
        onCopy?.(next)
    }

    return (
        <button
            onClick={handleCopy}
            key={`cmd-${copyKey}`}
            className={cn(
                'group inline-flex items-center gap-2 font-mono rounded-lg cursor-pointer transition-colors w-fit',
                sizeStyle.font,
                sizeStyle.padding,
                copyKey > 0 && 'CommandBlock__bounce',
                className
            )}
            type="button"
            aria-label={ariaLabel}
        >
            <IconTerminal className={cn(sizeStyle.icon, 'text-muted')} />
            <span className="relative">
                <code
                    className={cn('!bg-transparent !p-0 !border-0 select-all', {
                        'text-default': decoration === 'plain',
                        'rainbow-text': decoration === 'rainbow',
                        'rainbow-text-animating': decoration === 'rainbow' && !isStorybook,
                    })}
                >
                    {command}
                </code>
                {copyKey > 0 && (
                    <code
                        key={copyKey}
                        className="CommandBlock__flash !bg-transparent !p-0 !border-0"
                        aria-hidden="true"
                    >
                        {command}
                    </code>
                )}
            </span>
            <IconCopy className={cn(sizeStyle.icon, 'text-muted group-hover:text-primary')} />
        </button>
    )
}
