import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from './workflows'

/**
 * Whether a self-driving wizard run is going right now, for surfaces the run sends the user to
 * mid-flight (the GitHub connect round trip) that need to hand them back to their terminal.
 *
 * Registers the program with the detector while mounted rather than relying on the onboarding
 * variant flag, because the wizard is also run standalone against accounts that are long past
 * onboarding — those users would otherwise never be watched.
 */
export function useWizardRunInFlight(): boolean {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)
    const { watchWorkflow, unwatchWorkflow } = useActions(wizardActiveSessionDetectorLogic)

    useEffect(() => {
        watchWorkflow(SELF_DRIVING_WORKFLOW_ID)
        return () => unwatchWorkflow(SELF_DRIVING_WORKFLOW_ID)
    }, [watchWorkflow, unwatchWorkflow])

    return activeWorkflowId === SELF_DRIVING_WORKFLOW_ID
}
