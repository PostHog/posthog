import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { Breadcrumb } from '~/types'

export function SceneBreadcrumbBackButton({ forceBackTo }: { forceBackTo?: Breadcrumb }): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    const backTo = forceBackTo || breadcrumbs[breadcrumbs.length - 2]

    return breadcrumbs.length > 1 ? (
        <Link
            className="flex items-center gap-1 text-tertiary text-xs pl-[var(--button-padding-x-lg)]"
            aria-label={`Go back to ${backTo.name}`}
            to={backTo.path}
            buttonProps={{
                variant: 'default',
            }}
        >
            <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
            <span>{backTo.name}</span>
        </Link>
    ) : null
}
