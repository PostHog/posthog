import './CommandBlock.scss'

import { useRef, useState } from 'react'

import { IconCopy, IconTerminal } from '@posthog/icons'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

type Size = 'sm' | 'md'
type Decoration = 'plain' | 'rainbow'

const SIZE_STYLES: Record<Size, { padding: string; font: string; icon: string }> = {
    sm: { padding: 'px-2.5 py-1.5', font: 'text-xs', icon: 'size-3.5' },
    md: { padding: 'px-4 py-3', font: 'text-sm', icon: 'size-4' },
}

// A gentle squish-and-settle on copy. Played via the Web Animations API rather than by
// remounting the button (a remount would also restart the rainbow gradient scroll on the
// command text, making it visibly jump back to the start on every click).
const BOUNCE_KEYFRAMES: Keyframe[] = [
    { transform: 'scale(1)' },
    { transform: 'scale(0.985)', offset: 0.35 },
    { transform: 'scale(1.008)', offset: 0.7 },
    { transform: 'scale(1)' },
]

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
    const buttonRef = useRef<HTMLButtonElement>(null)
    const sizeStyle = SIZE_STYLES[size]
    const isStorybook = inStorybook() || inStorybookTestRunner()

    const handleCopy = (): void => {
        void copyToClipboard(command, copyLabel, { silent: silentCopy })
        const next = copyKey + 1
        setCopyKey(next)
        // WAAPI (not a CSS-class remount) so the bounce replays without resetting the rainbow scroll.
        // Guarded for jsdom, which doesn't implement `Element.animate`.
        const button = buttonRef.current
        if (button && typeof button.animate === 'function') {
            button.animate(BOUNCE_KEYFRAMES, { duration: 320, easing: 'ease-out' })
        }
        onCopy?.(next)
    }

    return (
        <button
            ref={buttonRef}
            onClick={handleCopy}
            className={cn(
                'group inline-flex items-center gap-2 font-mono rounded-lg cursor-pointer transition-colors w-fit',
                sizeStyle.font,
                sizeStyle.padding,
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
