import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { DEFAULT_MODEL, OBSERVATION_CREDITS_BY_MODEL } from 'products/replay_vision/frontend/replay_scanners/types'
import { getReplayVisionEditDisabledReason } from 'products/replay_vision/frontend/utils/accessControl'
import { formatCredits } from 'products/replay_vision/frontend/utils/credits'

import { experimentWizardLogic } from '../experimentWizardLogic'
import { ReplayVisionScannerCard, type ReplayVisionScannerOptionProps } from './ReplayVisionScannerCard'
import { ReplayVisionScannerCheckbox } from './ReplayVisionScannerCheckbox'

/** Turning this on opts the experiment into a Replay Vision scanner, created at save. The scanner
 * endpoint refuses without org AI approval, so turning it on without consent opens the consent popover
 * instead of letting the experiment save and the scanner fail after the fact.
 *
 * The `test` arm of EXPERIMENT_WIZARD_REPLAY_VISION_CARD shows it as a card with a toggle, `control` keeps the
 * checkbox. The flag is read here, at the end of the analytics step, so only people who see the option are
 * exposed. */
export function ReplayVisionScannerOption(): JSX.Element {
    const { createReplayVisionScanner } = useValues(experimentWizardLogic)
    const { setCreateReplayVisionScanner } = useActions(experimentWizardLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const optionProps: ReplayVisionScannerOptionProps = {
        checked: createReplayVisionScanner,
        onChange: (checked) => {
            if (checked && !dataProcessingAccepted) {
                setConsentRequested(true)
            } else {
                setCreateReplayVisionScanner(checked)
            }
        },
        disabledReason: getReplayVisionEditDisabledReason() ?? undefined,
        // Per-session price only: a monthly projection needs the 30-day recording history the
        // estimate endpoint reads, and an unstarted experiment has no exposed sessions yet, so
        // any monthly figure computed here would be a misleading zero. The scanner page shows
        // the projection once participant sessions exist. Priced at the model
        // experimentScannerBody pins, so this matches the scanner the save path creates.
        sessionPrice: formatCredits(OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL]),
    }

    const option =
        featureFlags[FEATURE_FLAGS.EXPERIMENT_WIZARD_REPLAY_VISION_CARD] === 'test' ? (
            <ReplayVisionScannerCard {...optionProps} />
        ) : (
            <ReplayVisionScannerCheckbox {...optionProps} />
        )

    if (dataProcessingAccepted) {
        return option
    }

    return (
        <AIConsentPopoverWrapper
            placement="top"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            hidden={!consentRequested}
            onApprove={() => {
                setConsentRequested(false)
                setCreateReplayVisionScanner(true)
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {option}
        </AIConsentPopoverWrapper>
    )
}
