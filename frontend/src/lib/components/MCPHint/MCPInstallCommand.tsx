import { useValues } from 'kea'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { MCP_INSTALL_COMMAND } from './constants'

type Size = 'sm' | 'md'

export function MCPInstallCommand({
    size = 'sm',
    className,
    silentCopy = false,
}: {
    size?: Size
    className?: string
    /** Skip the "Copied … to clipboard" toast (used when the parent is itself a toast). */
    silentCopy?: boolean
}): JSX.Element | null {
    const { isCloudOrDev } = useValues(preflightLogic)

    if (!isCloudOrDev) {
        return null
    }

    return (
        <CommandBlock
            command={MCP_INSTALL_COMMAND}
            copyLabel="MCP install command"
            ariaLabel="Copy MCP install command"
            size={size}
            decoration="rainbow"
            silentCopy={silentCopy}
            className={cn('bg-surface-secondary border border-primary !m-0 hover:border-accent', className)}
        />
    )
}
