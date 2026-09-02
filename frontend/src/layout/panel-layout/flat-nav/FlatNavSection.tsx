import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { Label } from 'lib/ui/Label/Label'

interface FlatNavSectionProps {
    label: string
    /** Short explanation of the section, shown behind an info icon next to the header. */
    info?: string
    /** Optional small control rendered at the right edge of the section header. */
    action?: React.ReactNode
    children: React.ReactNode
}

export function FlatNavSection({ label, info, action, children }: FlatNavSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-px mt-3">
            <div className="flex items-center justify-between pl-2 pr-1 min-h-5">
                <span className="flex items-center gap-1">
                    <Label intent="menu" className="text-xxs text-secondary">
                        {label}
                    </Label>
                    {info && (
                        <Tooltip title={info} placement="top">
                            <IconInfo className="size-3 text-tertiary" />
                        </Tooltip>
                    )}
                </span>
                {action}
            </div>
            {children}
        </div>
    )
}
