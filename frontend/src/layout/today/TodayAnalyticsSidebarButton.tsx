import { AutocompleteItem, Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SidebarButtonApi } from 'products/today/frontend/generated/api.schemas'

import { resolveSidebarTarget } from './todayAnalyticsSidebarTargets'

export function TodayAnalyticsSidebarButton({
    value,
    target,
    sectionId,
}: {
    value: string
    target: SidebarButtonApi
    sectionId: string
}): JSX.Element | null {
    const resolved = resolveSidebarTarget(target.to, target.label, target.icon)
    if (!resolved) {
        return null
    }
    return (
        <AutocompleteItem
            value={value}
            render={
                <Button
                    size="sm"
                    variant={target.variant ?? 'outline'}
                    nativeButton={false}
                    render={<LinkPrimitive to={resolved.to} />}
                    className="my-1 w-full justify-start data-highlighted:ring-2"
                />
            }
            data-attr={`analytics-sidebar-${sectionId}-button`}
        >
            {resolved.icon}
            <span className="truncate">{resolved.label}</span>
        </AutocompleteItem>
    )
}
