import { useValues } from 'kea'
import posthog from 'posthog-js'
import { Fragment } from 'react'

import { IconChevronDown, IconDatabase } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Text,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

import { todayShellLogic } from './todayShellLogic'
import { WarehouseItem, visibleWarehouseItems } from './todayWarehouseItems'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const GROUP_ORDER: WarehouseItem['group'][] = ['home', 'primary', 'secondary']

/** The bar above every warehouse page. Its menu is the only way to the warehouse tools under the rail navigation. */
export function TodayWarehouseHeader({ className }: { className?: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentWarehouseItem: current } = useValues(todayShellLogic)
    const items = visibleWarehouseItems(featureFlags)
    const groups = GROUP_ORDER.map((group) => items.filter((item) => item.group === group)).filter(
        (group) => group.length
    )

    return (
        <QuillSceneHeader
            className={cn('bg-chrome', className)}
            title={
                <>
                    <DropdownMenu>
                        <DropdownMenuTrigger render={<Button data-attr="today-warehouse-menu" />}>
                            <IconDatabase />
                            Warehouse
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="w-60">
                            {groups.map((group, index) => (
                                <Fragment key={group[0].group}>
                                    {index > 0 && <DropdownMenuSeparator />}
                                    {group.map((item) => (
                                        <DropdownMenuItem
                                            key={item.key}
                                            // quill draws the item as a row button, so a link keeps that look by rendering through one.
                                            render={
                                                <Button
                                                    size="row"
                                                    nativeButton={false}
                                                    left
                                                    className={cn(item.key === current?.key && 'bg-fill-selected')}
                                                    render={
                                                        <LinkPrimitive
                                                            to={item.href}
                                                            aria-current={
                                                                item.key === current?.key ? 'page' : undefined
                                                            }
                                                        />
                                                    }
                                                />
                                            }
                                            onClick={() =>
                                                posthog.capture('warehouse menu item clicked', {
                                                    item: item.key,
                                                    from: current?.key ?? null,
                                                })
                                            }
                                            data-attr={`today-warehouse-menu-${item.key}`}
                                        >
                                            {iconForType(item.iconType)}
                                            {item.label}
                                        </DropdownMenuItem>
                                    ))}
                                </Fragment>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    {current && current.key !== 'home' && (
                        <Text size="sm" variant="muted" className="min-w-0 truncate">
                            {current.label}
                        </Text>
                    )}
                </>
            }
        />
    )
}
