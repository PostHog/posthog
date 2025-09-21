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
            className={cn('flex items-center gap-1 text-tertiary hover:text-accent text-[0.8125rem]', className)}
            aria-label={`Go back to ${backTo.name}`}
            to={backTo.path}
        >
            <IconArrowLeft aria-hidden="true" className="size-3" />
            <span>{backTo.name}</span>
        </Link>
    ) : null
}
