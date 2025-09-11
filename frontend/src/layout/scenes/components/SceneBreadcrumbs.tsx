import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

export function SceneBreadcrumbBackButton(): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    return breadcrumbs.length > 1 ? (
        <Link
            className="flex items-center gap-1 text-tertiary text-xs pl-[var(--button-padding-x-lg)]"
            aria-label={`Go back to ${breadcrumbs[breadcrumbs.length - 2].name}`}
            to={breadcrumbs[breadcrumbs.length - 2].path}
            buttonProps={{
                variant: 'default',
            }}
        >
            <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
            <span>{breadcrumbs[breadcrumbs.length - 2].name}</span>
        </Link>
    ) : null
}
