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

    const BackToProps = {
        'aria-label': `Go back to ${backTo.name}`,
        to: backTo.path,
    }

    return !!forceBackTo || breadcrumbs.length > 1 ? (
        <>
            <Link
                {...BackToProps}
                className={cn('items-center gap-1 text-tertiary text-xs', className)}
                buttonProps={{
                    variant: 'default',
                    iconOnly: true,
                }}
                tooltip={<>Go back to {backTo.name}</>}
            >
                <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
            </Link>
        </>
    ) : null
}
