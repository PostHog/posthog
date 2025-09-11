import React from 'react'

import { WarningHog } from 'lib/components/hedgehogs'

export interface BillingEmptyStateProps {
    heading?: string
    detail?: string | React.ReactNode
}

export function BillingEmptyState({
    heading = 'No data available',
    detail = 'Please try adjusting your query or filters.',
}: BillingEmptyStateProps): JSX.Element {
    return (
        <div
            data-attr="billing-empty-state"
            className="flex flex-col bg-white rounded px-4 py-8 items-center text-center mx-auto"
        >
            <WarningHog width="100" height="100" className="mb-4" />
            <h2 className="text-xl leading-tight">{heading}</h2>
            {typeof detail === 'string' ? (
                <p className="text-sm text-balance text-tertiary">{detail}</p>
            ) : (
                <div className="text-sm text-balance text-tertiary">{detail}</div>
            )}
        </div>
    )
}
