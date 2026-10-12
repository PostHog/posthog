import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'

import { WorkflowSuggestionAvailabilityContext } from 'products/posthog_ai/frontend/api/runner'

/**
 * The server offers a workflow only to the AI-first variant, so this checks the rest of the builder's gate.
 * Reading the variant here would record an experiment exposure on every page.
 */
export function WorkflowSuggestionAvailabilityProvider({ children }: { children: ReactNode }): JSX.Element {
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    return (
        <WorkflowSuggestionAvailabilityContext.Provider value={sceneIntegrationEnabled}>
            {children}
        </WorkflowSuggestionAvailabilityContext.Provider>
    )
}
