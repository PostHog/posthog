import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { JourneyBuilder } from '../../components/CustomerJourneys/JourneyBuilder'
import { journeyBuilderLogic } from '../../components/CustomerJourneys/journeyBuilderLogic'
import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'

export const scene: SceneExport = {
    component: CustomerJourneyBuilderScene,
    logic: journeyBuilderLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}

export function CustomerJourneyBuilderScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={customerAnalyticsFeaturePreviewGate}>
            <CustomerJourneyBuilderSceneContent />
        </FeaturePreviewSceneGate>
    )
}

function CustomerJourneyBuilderSceneContent(): JSX.Element {
    const { journeyName, journeyDescription, isSaving, isEditMode } = useValues(journeyBuilderLogic)
    const { setJourneyName, setJourneyDescription, saveJourney } = useActions(journeyBuilderLogic)

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={journeyName}
                description={journeyDescription}
                resourceType={{ type: 'funnel' }}
                onNameChange={setJourneyName}
                onDescriptionChange={setJourneyDescription}
                descriptionMaxLength={400}
                canEdit={!accessControlDisabledReason}
                forceEdit
                renameDebounceMs={0}
                saveOnBlur
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={isSaving}
                        onClick={() => saveJourney()}
                        data-attr="journey-builder-save"
                        disabledReason={accessControlDisabledReason}
                    >
                        {isEditMode ? 'Update' : 'Save'}
                    </LemonButton>
                }
            />
            <JourneyBuilder />
        </SceneContent>
    )
}
