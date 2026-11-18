import { type LogicWrapper, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import type { ProductKey } from '~/queries/schema/schema-general'

import { productSetupStatusLogic } from './productSetupStatusLogic'

export interface SetupListeningIndicatorProps {
    productKey: ProductKey
    /** The product's detection logic, the same one its empty state declares as `statusLogic`. */
    statusLogic: LogicWrapper
    dataName: string
    destination: { label: string; url: string }
}

export function SetupListeningIndicator({
    productKey,
    statusLogic,
    dataName,
    destination,
}: SetupListeningIndicatorProps): JSX.Element {
    useMountedLogic(statusLogic)
    const { status } = useValues(productSetupStatusLogic({ productKey }))

    if (status === 'has-data') {
        return (
            <div className="flex flex-wrap items-center gap-2 rounded border border-success p-2 text-sm">
                <IconCheckCircle className="text-lg text-success" />
                <span className="flex-1">Your first {dataName} arrived.</span>
                <LemonButton
                    type="primary"
                    size="small"
                    to={destination.url}
                    data-attr={`${productKey}-setup-go-to-product`}
                >
                    Go to {destination.label}
                </LemonButton>
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
