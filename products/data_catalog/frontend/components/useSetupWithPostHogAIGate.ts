import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { urls } from 'scenes/urls'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { CatalogSetupSource, catalogSetupLogic } from '../catalogSetupLogic'
import { AIConsentGate, useAIConsentGate } from './useAIConsentGate'

export function useSetupWithPostHogAIGate(source: CatalogSetupSource): AIConsentGate {
    const { startSetupWithPostHogAI, rememberSetupIntent, resumeSetupIntent } = useActions(catalogSetupLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const consentGate = useAIConsentGate(() => startSetupWithPostHogAI(source), {
        onBeforeApprove: () => rememberSetupIntent(source),
        pendingRedirectUrl: urls.dataCatalog('metrics'),
    })

    // Finishes a click that an SSO reauthentication interrupted, once consent is in place. While the
    // popover is open, `onApprove` starts setup itself, so resuming then would start it twice. The open
    // state belongs to this button, so the resume lives here and not in the logic.
    useEffect(() => {
        if (dataProcessingAccepted && !consentGate.consentOpen) {
            resumeSetupIntent()
        }
    }, [dataProcessingAccepted, consentGate.consentOpen, resumeSetupIntent])

    return consentGate
}
