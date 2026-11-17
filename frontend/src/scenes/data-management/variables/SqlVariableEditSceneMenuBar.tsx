import { useActions, useValues } from 'kea'

import { IconCheck, IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { sqlVariableEditSceneLogic } from './sqlVariableEditSceneLogic'

const RESOURCE_TYPE = 'sql-variable'

export function SqlVariableEditSceneMenuBar({ discardChanges }: { discardChanges: () => void }): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <SqlVariableEditSceneMenuBarInner discardChanges={discardChanges} /> : null
}

function SqlVariableEditSceneMenuBarInner({ discardChanges }: { discardChanges: () => void }): JSX.Element {
    const { isNew, hasChanges, isVariableFormSubmitting } = useValues(sqlVariableEditSceneLogic)
    const { submitVariableForm } = useActions(sqlVariableEditSceneLogic)
    const unchanged = !isNew && !hasChanges
    const saveDisabledReason = unchanged ? 'No changes to save' : undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label: 'Save',
            icon: <IconCheck />,
            disabledReason: isVariableFormSubmitting ? 'Saving variable' : saveDisabledReason,
            onSelect: submitVariableForm,
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <Button
                        data-attr="save-variable"
                        variant="primary"
                        onClick={submitVariableForm}
                        loading={isVariableFormSubmitting}
                        disabledReason={saveDisabledReason}
                    >
                        Save
                    </Button>
                ),
            },
        },
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-discard-changes`,
            label: 'Discard changes',
            icon: <IconUndo />,
            disabledReason: unchanged ? 'No changes to discard' : undefined,
            onSelect: discardChanges,
            pinned: { order: 2, variant: 'secondary', dataAttr: 'discard-variable-changes' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
