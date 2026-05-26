import { useValues } from 'kea'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { MCP_INSTALL_COMMAND } from './constants'

type Size = 'sm' | 'md'

export function MCPInstallCommand({ size = 'sm', className }: { size?: Size; className?: string }): JSX.Element | null {
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
            className={cn('bg-surface-secondary border border-primary !m-0 hover:border-accent', className)}
        />
    )
}
