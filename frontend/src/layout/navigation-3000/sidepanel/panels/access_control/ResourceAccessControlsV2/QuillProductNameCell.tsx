import type { CellContext } from '@tanstack/react-table'

import { IconInfo } from '@posthog/icons'
import { Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject } from '~/types'

import { ScopeIcon } from './ScopeIcon'

export type ProductRow = { key: APIScopeObject; label: string }

export function QuillProductNameCell({ row }: CellContext<ProductRow, unknown>): JSX.Element {
    const tooltipText = getAccessControlTooltip(row.original.key)

    return (
        <div className="flex items-center gap-2">
            <span className="flex items-center text-muted-foreground">
                <ScopeIcon scope={row.original.key} />
            </span>
            <Text size="xs" weight="medium" render={<span />}>
                {row.original.label}
            </Text>
            {tooltipText && (
                <Tooltip>
                    <TooltipTrigger render={<span className="flex items-center text-muted-foreground" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent>{tooltipText}</TooltipContent>
                </Tooltip>
            )}
        </div>
    )
}
