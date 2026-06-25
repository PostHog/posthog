import { useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useState } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { AgentBadgeRotator } from 'lib/components/MCPHint/AgentBadgeRotator'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

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
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISSED_KEY) === '1')

    // The wizard CLI only targets cloud (US/EU) and dev instances — self-hosted has no
    // preconfigured endpoint, so hide it rather than show a command that can't work.
    if (!isCloudOrDev || dismissed) {
        return fallback ? <>{fallback}</> : null
    }

    const region = preflight?.region || Region.US
    const command = `npx -y @posthog/wizard@latest warehouse${region === Region.EU ? ' --region eu' : ''}`

    const handleDismiss = (): void => {
        localStorage.setItem(DISMISSED_KEY, '1')
        setDismissed(true)
        posthog.capture('warehouse wizard hint dismissed')
    }

    return (
        <div
            className={cn(
                'relative rounded-lg border border-dashed border-primary bg-bg-light p-4 flex flex-col gap-3',
                className
            )}
        >
            <LemonButton
                icon={<IconX />}
                size="xsmall"
                onClick={handleDismiss}
                className="absolute top-2 right-2"
                tooltip="Dismiss"
                aria-label="Dismiss"
            />
            <div className="flex items-center gap-2 pr-6">
                <IconSparkles className="size-4 shrink-0" />
                <h4 className="m-0 text-sm font-semibold">
                    Let <AgentBadgeRotator /> connect your sources for you
                </h4>
            </div>
            <div className="text-sm text-default">
                Skip the manual setup — run this in your project and the wizard auto-detects your databases and APIs and
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
        </div>
    )
}
