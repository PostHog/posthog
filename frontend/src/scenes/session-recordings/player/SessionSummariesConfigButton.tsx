import { useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconPencil } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { SessionSummariesConfigDrawer } from './SessionSummariesConfigDrawer'
import { sessionSummariesConfigLogic } from './sessionSummariesConfigLogic'

export function SessionSummariesConfigButton(): JSX.Element {
    const [isDrawerOpen, setIsDrawerOpen] = useState(false)
    const { config, isLoading } = useValues(sessionSummariesConfigLogic)

    const hasContext = !!config?.product_context?.trim()
    const label = hasContext ? 'Edit product context' : 'Add product context'
    const tooltip = hasContext
        ? 'Your team has AI product context set. This is injected into every replay summary.'
        : 'Optional: tell the AI about your product so summaries read with the right context.'

    return (
        <>
            <Tooltip title={tooltip}>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={hasContext ? <IconPencil /> : <IconInfo />}
                    data-attr="session-summary-edit-product-context"
                    disabled={isLoading}
                    onClick={() => setIsDrawerOpen(true)}
                >
                    {label}
                </LemonButton>
            </Tooltip>
            <SessionSummariesConfigDrawer isOpen={isDrawerOpen} onClose={() => setIsDrawerOpen(false)} />
        </>
    )
}
