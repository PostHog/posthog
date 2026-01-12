import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { Link } from 'lib/lemon-ui/Link'

const SUPPORTED_RUNTIMES = ['python']

export function CodeVariablesInlineBanner(): JSX.Element | null {
    const { exceptionAttributes } = useValues(errorPropertiesLogic)

    const dismissLogic = lemonBannerLogic({
        dismissKey: `code-variables-inline-banner-${exceptionAttributes?.runtime}`,
    })
    const { isDismissed } = useValues(dismissLogic)
    const { dismiss } = useActions(dismissLogic)

    const isSupportedRuntime = exceptionAttributes?.runtime && SUPPORTED_RUNTIMES.includes(exceptionAttributes.runtime)

    if (!isSupportedRuntime || isDismissed) {
        return null
    }

    return (
        <div className="border-t border-border bg-fill-secondary px-3 py-2 text-xs text-muted-alt">
            <div className="flex items-center justify-between gap-2">
                <div className="flex-1">
                    <span className="italic">Code variables would appear here. </span>
                    <Link
                        className="font-medium"
                        to={`https://posthog.com/docs/error-tracking/code-variables/${exceptionAttributes.runtime}`}
                        target="_blank"
                    >
                        Learn how to enable them
                    </Link>
                </div>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={dismiss}
                    tooltip="Dismiss"
                    className="text-muted-alt hover:text-default"
                />
            </div>
        </div>
    )
}
