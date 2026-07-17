import clsx from 'clsx'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/** Fallback card for signals without a dedicated renderer. Shows content, timestamp, and raw metadata. */
export function GenericSignalCard({ signal }: SignalCardProps): JSX.Element {
    const [showRaw, setShowRaw] = useState(false)

    return (
        <SignalCardShell signal={signal}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <div className="text-xs text-tertiary">
                <TZLabel time={signal.timestamp} />
            </div>

            {Object.keys(signal.extra).length > 0 && (
                <div className="mt-2">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => setShowRaw(!showRaw)}
                        icon={
                            <IconChevronRight className={clsx('size-3 transition-transform', showRaw && 'rotate-90')} />
                        }
                    >
                        Raw metadata
                    </LemonButton>
                    {showRaw && (
                        <pre className="text-xs mt-1 p-2 bg-surface-secondary rounded overflow-x-auto max-h-60">
                            {JSON.stringify(signal.extra, null, 2)}
                        </pre>
                    )}
                </div>
            )}
        </SignalCardShell>
    )
}
