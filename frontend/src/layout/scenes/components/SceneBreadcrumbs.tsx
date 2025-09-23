import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { Breadcrumb } from '~/types'

interface SceneBreadcrumbBackButtonProps {
    forceBackTo?: Breadcrumb
    className?: string
}

export function SceneBreadcrumbBackButton({
    forceBackTo,
    className,
}: SceneBreadcrumbBackButtonProps): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    const backTo = forceBackTo || breadcrumbs[breadcrumbs.length - 2]

    return !!forceBackTo || breadcrumbs.length > 1 ? (
        <Link
            className={cn('flex items-center gap-1 text-tertiary text-xs pl-[var(--button-padding-x-lg)]', className)}
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
