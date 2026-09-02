import { ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

export interface AccountWidgetHeaderProps {
    icon: ReactNode
    title: string
    /** Extra chrome after the title, such as a cadence tag. */
    titleExtra?: ReactNode
    /** Right-aligned text or controls. */
    meta?: ReactNode
    onRefresh?: () => void
    onConfigure?: () => void
    onRemove: () => void
    className?: string
    'data-attr'?: string
}

export function AccountWidgetHeader({
    icon,
    title,
    titleExtra,
    meta,
    onRefresh,
    onConfigure,
    onRemove,
    className,
    'data-attr': dataAttr,
}: AccountWidgetHeaderProps): JSX.Element {
    const items: LemonMenuItems = [
        onRefresh ? { label: 'Refresh', onClick: onRefresh } : null,
        onConfigure ? { label: 'Configure', onClick: onConfigure } : null,
        { label: 'Remove from view', status: 'danger', onClick: onRemove },
    ]

    return (
        <div className={className ?? 'flex items-center gap-2 px-3 py-2 border-b'} data-attr={dataAttr}>
            <span className="flex items-center text-secondary text-base">{icon}</span>
            <span className="text-sm font-semibold truncate">{title}</span>
            {titleExtra}
            <div className="ml-auto flex items-center gap-2 text-xs text-secondary min-w-0">
                {meta}
                <LemonMenu items={items} placement="bottom-end">
                    <LemonButton
                        size="xsmall"
                        icon={<IconEllipsis />}
                        aria-label={`${title} options`}
                        data-attr="account-widget-menu"
                    />
                </LemonMenu>
            </div>
        </div>
    )
}
