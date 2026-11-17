import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCheck, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { DefinitionLogicProps, definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'definition-edit'

export function DefinitionEditSceneMenuBar(props: DefinitionLogicProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <DefinitionEditSceneMenuBarInner {...props} /> : null
}

function DefinitionEditSceneMenuBarInner(props: DefinitionLogicProps): JSX.Element {
    const { definitionLoading, isProperty } = useValues(definitionLogic(props))
    const { editDefinition } = useValues(definitionEditLogic(props))
    const { saveDefinition } = useActions(definitionEditLogic(props))
    const loadingReason = definitionLoading ? 'Loading definition' : undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label: 'Save',
            icon: <IconCheck />,
            disabledReason: loadingReason,
            onSelect: () => saveDefinition({}),
            pinned: { order: 1, variant: 'primary', dataAttr: 'save-definition' },
        },
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            disabledReason: loadingReason,
            onSelect: () =>
                router.actions.push(
                    isProperty ? urls.propertyDefinition(editDefinition.id) : urls.eventDefinition(editDefinition.id)
                ),
            pinned: { order: 2, variant: 'secondary', dataAttr: 'cancel-definition' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
