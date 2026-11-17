import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { journeyBuilderLogic } from '../../components/CustomerJourneys/journeyBuilderLogic'

const RESOURCE_TYPE = 'customer-journey-builder'

export function CustomerJourneyBuilderSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <CustomerJourneyBuilderSceneMenuBarInner /> : null
}

function CustomerJourneyBuilderSceneMenuBarInner(): JSX.Element {
    const { isSaving, isEditMode } = useValues(journeyBuilderLogic)
    const { saveJourney } = useActions(journeyBuilderLogic)
    const accessControlDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Editor) ??
        undefined
    const label = isEditMode ? 'Update' : 'Save'

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label,
            icon: <IconCheck />,
            disabledReason: accessControlDisabledReason ?? (isSaving ? 'Saving the journey' : undefined),
            onSelect: () => saveJourney(),
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <Button
                        variant="primary"
                        loading={isSaving}
                        onClick={() => saveJourney()}
                        data-attr="journey-builder-save"
                        disabledReason={accessControlDisabledReason}
                    >
                        {label}
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
