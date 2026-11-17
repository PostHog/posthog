import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Scene } from 'scenes/sceneTypes'

import { annotationModalLogic } from '../logics/annotationModalLogic'

export function NewAnnotationButton(): JSX.Element {
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <Shortcut
            name="NewAnnotation"
            keybind={[keyBinds.new]}
            intent="New annotation"
            interaction="click"
            scope={Scene.Annotations}
        >
            {todayRailNav ? (
                <Button
                    variant="primary"
                    data-attr="create-annotation"
                    onClick={() => openModalToCreateAnnotation()}
                    tooltip="New annotation"
                >
                    New annotation
                </Button>
            ) : (
                <LemonButton
                    type="primary"
                    data-attr="create-annotation"
                    onClick={() => openModalToCreateAnnotation()}
                    size="small"
                    tooltip="New annotation"
                >
                    New annotation
                </LemonButton>
            )}
        </Shortcut>
    )
}
