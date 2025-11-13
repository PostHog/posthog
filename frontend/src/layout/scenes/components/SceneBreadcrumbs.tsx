import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { ButtonGroupPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { capitalizeFirstLetter } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
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
    const { backToUrl: logicalBackToUrl } = useValues(navigationLogic)
    const { clearBackToUrl } = useActions(navigationLogic)

    const backTo = forceBackTo || breadcrumbs[breadcrumbs.length - 2]

    const normalBackTo = {
        ariaLabel: `Go back to ${backTo.name}`,
        to: backTo.path,
    }

    const logicBackTo = logicalBackToUrl
        ? {
              ariaLabel: `Go back to ${logicalBackToUrl.name}`,
              to: logicalBackToUrl.url,
          }
        : null

    // Only show back-to-url button if current URL matches the destination URL set with setBackToUrl action before navigating
    const currentUrl = removeProjectIdIfPresent(router.values.location.pathname)
    const destinationUrl = removeProjectIdIfPresent(logicalBackToUrl?.destinationUrl ?? '')
    const shouldShowLogicalBackButton = logicalBackToUrl && destinationUrl.startsWith(currentUrl)

    return !!forceBackTo || breadcrumbs.length > 1 || !!shouldShowLogicalBackButton ? (
        <>
            <ButtonGroupPrimitive groupVariant="outline" className="mr-1">
                {/* Show the back button based on breadcrumbs / forced back to  */}
                {!shouldShowLogicalBackButton && (!!forceBackTo || breadcrumbs.length > 1) && (
                    <Link
                        {...normalBackTo}
                        className={cn('items-center gap-1 text-tertiary text-xs', className)}
                        buttonProps={{
                            iconOnly: true,
                        }}
                        tooltip={<>Go back to {backTo.name}</>}
                        tooltipCloseDelayMs={0}
                    >
                        <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
                    </Link>
                )}
                {/* Show the back button based on setBackToUrl action, which you call before navigating */}
                {shouldShowLogicalBackButton && (
                    <Link
                        {...logicBackTo}
                        className={cn('items-center gap-1 text-tertiary text-xs ', className)}
                        buttonProps={{
                            iconOnly: true,
                        }}
                        onClick={() => {
                            // On click, clear the logical back to url, so the back button is not shown again
                            clearBackToUrl()
                        }}
                        tooltip={
                            <>
                                Go back to {capitalizeFirstLetter(logicalBackToUrl.resourceType)}:{' '}
                                {logicalBackToUrl.name}
                            </>
                        }
                        tooltipCloseDelayMs={0}
                    >
                        <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
                    </Link>
                )}
            </ButtonGroupPrimitive>
        </>
    ) : null
}
