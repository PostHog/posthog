import { useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { AgentBadgeRotator } from 'lib/components/MCPHint/AgentBadgeRotator'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

// Persist dismissal so the hint doesn't nag a user who has seen it. Mirrors the MCP hint cards.
const DISMISSED_KEY = 'warehouse-wizard-hint-dismissed'

/**
 * Agent-flavored nudge shown above the new-source catalog, mirroring the MCP hint card style:
 * pushes the `npx @posthog/wizard warehouse` CLI, which auto-detects and connects a user's
 * databases/APIs straight from their codebase instead of filling in the forms by hand.
 */
export function WarehouseWizardHint({
    className,
    fallback,
}: {
    className?: string
    /** Rendered in place of the hint when it can't show (self-hosted or already dismissed). Lets a
     *  host surface another nudge there — e.g. the SQL editor falls back to its MCP hint — so the
     *  two are mutually exclusive and never stack. */
    fallback?: ReactNode
}): JSX.Element | null {
    const { isCloudOrDev } = useValues(preflightLogic)
    const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISSED_KEY) === '1')

    // The wizard CLI only targets cloud (US/EU) and dev instances — self-hosted has no
    // preconfigured endpoint, so hide it rather than show a command that can't work.
    if (!isCloudOrDev || dismissed) {
        return fallback ? <>{fallback}</> : null
    }

    const command = `npx -y @posthog/wizard@latest warehouse`

    const handleDismiss = (): void => {
        localStorage.setItem(DISMISSED_KEY, '1')
        setDismissed(true)
        posthog.capture('warehouse wizard hint dismissed')
    }

    return (
        <div
            className={cn(
                'rounded-lg border border-dashed border-primary bg-bg-light p-4 flex flex-col gap-3',
                className
            )}
        >
            <div className="flex items-center gap-2">
                <IconSparkles className="size-4 shrink-0" />
                <h4 className="m-0 text-sm font-semibold">
                    Let <AgentBadgeRotator /> connect your sources for you
                </h4>
            </div>
            <div className="text-sm text-default">
                Skip the manual setup. Run this in your project and the wizard finds your databases and APIs and
                connects them to PostHog.
            </div>
            <div className="pt-1">
                <CommandBlock
                    command={command}
                    copyLabel="Data warehouse wizard command"
                    ariaLabel="Copy data warehouse wizard command"
                    size="sm"
                    decoration="rainbow"
                    className="bg-surface-secondary border border-primary !m-0 hover:border-accent"
                    onCopy={() => posthog.capture('warehouse wizard hint command copied')}
                />
            </div>
            <div className="flex justify-end">
                <LemonButton size="xsmall" type="tertiary" onClick={handleDismiss}>
                    Dismiss
                </LemonButton>
            </div>
        </div>
    )
}
