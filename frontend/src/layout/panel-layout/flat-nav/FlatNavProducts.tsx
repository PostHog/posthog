import { useValues } from 'kea'
import posthog from 'posthog-js'
import { Fragment } from 'react'

import { IconGear } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { urls } from 'scenes/urls'

import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { flatNavLogic } from './flatNavLogic'
import { FlatNavSection } from './FlatNavSection'

function slugify(path: string): string {
    return path.toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

export function FlatNavProducts(): JSX.Element {
    const { productGroups, customProductsLoading } = useValues(flatNavLogic)

    return (
        <FlatNavSection
            label="My tools"
            action={
                <Link
                    to={urls.settings('user-navigation')}
                    tooltip="Choose which tools to show in the sidebar"
                    tooltipPlacement="top"
                    onClick={() => posthog.capture('nav tools customize clicked')}
                    buttonProps={{ iconOnly: true, size: 'xs' }}
                    data-attr="flat-nav-tools-customize-button"
                >
                    <IconGear className="size-3 text-secondary" />
                </Link>
            }
        >
            <div className="flex flex-col gap-px group/colorful-product-icons colorful-product-icons-true">
                {customProductsLoading && productGroups.length === 0 ? (
                    Array.from({ length: 4 }).map((_, index) => (
                        <WrappingLoadingSkeleton fullWidth key={index}>
                            <ButtonPrimitive aria-hidden inert menuItem />
                        </WrappingLoadingSkeleton>
                    ))
                ) : productGroups.length === 0 ? (
                    <span className="text-xs text-tertiary px-2 py-1">
                        No tools selected. Use the gear icon above to pick some.
                    </span>
                ) : (
                    productGroups.map((group) => (
                        <Fragment key={group.category}>
                            {group.category && (
                                <div className="not-first:mt-3 py-1 px-2 flex items-center">
                                    <span className="text-xs font-semibold text-tertiary">{group.category}</span>
                                </div>
                            )}
                            {group.items.map((item) => (
                                <NavLink
                                    key={item.path}
                                    to={item.href}
                                    label={item.label}
                                    icon={iconForType(item.iconType, item.iconColor)}
                                    isCollapsed={false}
                                    tag={item.tag}
                                    data-attr={`flat-nav-tool-${slugify(item.path)}`}
                                    onClick={() => posthog.capture('nav item clicked', { item: item.path })}
                                />
                            ))}
                        </Fragment>
                    ))
                )}
            </div>
        </FlatNavSection>
    )
}
