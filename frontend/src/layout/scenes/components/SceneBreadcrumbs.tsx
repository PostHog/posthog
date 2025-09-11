import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

export function SceneBreadcrumbBackButton(): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    return breadcrumbs.length > 2 ? (
        <Link
            className="flex items-center gap-1 text-tertiary text-xs pl-[var(--button-padding-x-lg)]"
            aria-label={`Go back to ${breadcrumbs[1].name}`}
            to={breadcrumbs[1].path}
            buttonProps={{
                variant: 'default',
            }}
        >
            <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
            <span>{breadcrumbs[1].name}</span>
        </Link>
    ) : null
}
