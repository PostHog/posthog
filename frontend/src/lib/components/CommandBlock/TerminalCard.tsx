import './TerminalCard.scss'

import { useState } from 'react'

import { IconCheck, IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { condenseCommand } from './CommandBlock'

const COPIED_RESET_MS = 1700

interface TerminalCardProps {
    command: string
    /** Label passed to the copy-to-clipboard toast (e.g. "MCP wizard command"). */
    copyLabel: string
    className?: string
}

/**
 * A dark terminal-chrome card that types its command out with a blinking caret.
 * The hero treatment for install commands on product empty states — for a compact
 * inline command pill, use `CommandBlock` instead.
 *
 * Styled with tailwind except the typewriter/caret animations (TerminalCard.scss):
 * a `steps(var(--steps))` timing function and a `width: var(--chars)` keyframe
 * can't be expressed as utilities.
 */
export function TerminalCard({ command, copyLabel, className }: TerminalCardProps): JSX.Element {
    const [copied, setCopied] = useState(false)

    // Freeze the typewriter in storybook so visual snapshots are deterministic.
    const isStatic = inStorybook() || inStorybookTestRunner()

    // Show the command without `-y`/`@latest` noise; the full `command` is still what gets copied.
    const displayCommand = condenseCommand(command)

    const handleCopy = (): void => {
        void copyToClipboard(command, copyLabel)
        setCopied(true)
        window.setTimeout(() => setCopied(false), COPIED_RESET_MS)
    }

    return (
        // Deliberately dark in both themes (primitive grays don't flip with the theme): it's a terminal.
        <div className={cn('overflow-hidden rounded border border-gray-700 bg-gray-900 text-[0.8125rem]', className)}>
            <div className="flex items-center gap-1.5 border-b border-gray-700 bg-gray-800 px-2.5 py-1.5">
                <span className="size-2.5 rounded-full bg-red-500" />
                <span className="size-2.5 rounded-full bg-yellow-400" />
                <span className="size-2.5 rounded-full bg-[var(--color-green-500)]" />
                <span className="ml-1.5 flex-1 font-mono text-[0.6875rem] text-gray-400">bash</span>

                <LemonButton
                    size="xsmall"
                    icon={copied ? <IconCheck /> : <IconCopy />}
                    onClick={handleCopy}
                    // Force white regardless of theme: LemonButton colors its inner chrome via
                    // `--lemon-button-color`, so overriding that (not `text-white`) is what actually lands.
                    className="[--lemon-button-color:#fff] [--lemon-button-icon-opacity:1]"
                    aria-label={`Copy command: ${command}`}
                >
                    {copied ? 'Copied' : 'Copy'}
                </LemonButton>
            </div>
            <div className="flex items-baseline gap-2 overflow-x-auto whitespace-nowrap px-4 py-3.5 font-mono">
                <span className="select-none text-[var(--color-green-500)]">$</span>
                <span className="inline-flex min-w-0 items-baseline">
                    <code
                        className={cn(
                            'inline-block max-w-full overflow-hidden whitespace-nowrap !border-0 !bg-transparent !p-0 text-gray-100',
                            'TerminalCard__cmd',
                            isStatic && 'TerminalCard__cmd--static'
                        )}
                        // The typewriter reveals the command by animating width in `ch` units,
                        // so the CSS needs the character count.
                        style={
                            {
                                '--terminal-cmd-chars': `${displayCommand.length}ch`,
                                '--terminal-cmd-steps': displayCommand.length,
                            } as React.CSSProperties
                        }
                    >
                        {displayCommand}
                    </code>
                    <span
                        className={cn(
                            'ml-0.5 inline-block h-[1em] w-[7px] self-center bg-gray-100',
                            'TerminalCard__caret',
                            isStatic && 'TerminalCard__caret--static'
                        )}
                        aria-hidden="true"
                    />
                </span>
            </div>
        </div>
    )
}
