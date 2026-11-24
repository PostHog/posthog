import { type LogicWrapper, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconInfo } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import type { ProductKey } from '~/queries/schema/schema-general'

import { productSetupStatusLogic } from './productSetupStatusLogic'

export interface SetupListeningIndicatorDestination {
    label: string
    /** Where the button links to. Pass `onClick` instead when the click has to run a flow, such as finishing onboarding. */
    url?: string
    onClick?: () => void
}

export interface SetupListeningIndicatorProps {
    productKey: ProductKey
    /** The product's detection logic, the same one its empty state declares as `statusLogic`. */
    statusLogic: LogicWrapper
    dataName: string
    destination: SetupListeningIndicatorDestination
}

export function SetupListeningIndicator({
    productKey,
    statusLogic,
    dataName,
    destination,
}: SetupListeningIndicatorProps): JSX.Element {
    useMountedLogic(statusLogic)
    const { status } = useValues(productSetupStatusLogic({ productKey }))

    const button = (
        <LemonButton
            type={status === 'has-data' ? 'primary' : 'secondary'}
            size="small"
            to={destination.url}
            onClick={destination.onClick}
            data-attr={`${productKey}-setup-go-to-product`}
        >
            {destination.label}
        </LemonButton>
    )

    if (status === 'has-data') {
        return (
            <div className="flex flex-wrap items-center gap-2 rounded border border-success p-2 text-sm">
                <IconCheckCircle className="text-lg text-success" />
                <span className="flex-1">Your first {dataName} arrived.</span>
                {button}
            </div>
        )
    }
    if (status === 'unknown') {
        // Detection could not run (no access, or the check failed), so there is nothing to listen for.
        // Sending data won't change this, so point at the product instead of promising a result.
        return (
            <div className="flex flex-wrap items-center gap-2 rounded border border-primary p-2 text-sm text-secondary">
                <IconInfo className="text-lg" />
                <span className="flex-1">We can't check for incoming {dataName}s right now.</span>
                {button}
            </div>
        )
    }
    return (
        <div className="flex items-center gap-2 rounded border border-primary p-2 text-sm text-secondary">
            <Spinner />
            <span>
                Listening for your first {dataName}. It usually shows up within a minute of restarting your services.
            </span>
        </div>
    )
}
