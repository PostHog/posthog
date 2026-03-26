import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'

import { JourneyBuilder } from '../../components/CustomerJourneys/JourneyBuilder'
import { journeyBuilderLogic } from '../../components/CustomerJourneys/journeyBuilderLogic'

export const scene: SceneExport = {
    component: CustomerJourneyBuilderScene,
    logic: journeyBuilderLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}

export function CustomerJourneyBuilderScene(): JSX.Element {
    const { journeyName, journeyDescription, isSaving, isEditMode } = useValues(journeyBuilderLogic)
    const { setJourneyName, setJourneyDescription, saveJourney } = useActions(journeyBuilderLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={journeyName}
                description={journeyDescription}
                resourceType={{ type: 'funnel' }}
                onNameChange={setJourneyName}
                onDescriptionChange={setJourneyDescription}
                descriptionMaxLength={400}
                canEdit
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
                    >
                        {isEditMode ? 'Update' : 'Save'}
                    </LemonButton>
                }
            />
            <JourneyBuilder />
        </SceneContent>
    )
}
