import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function NewNotebookButton(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Notebook}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Shortcut
                name="NewNotebook"
                keybind={[keyBinds.new]}
                intent="New notebook"
                interaction="click"
                scope={Scene.Notebooks}
            >
                {todayRailNav ? (
                    <Button
                        data-attr="new-notebook"
                        render={<LinkPrimitive to={urls.notebook('new')} />}
                        variant="primary"
                        tooltip="New notebook"
                    >
                        New notebook
                    </Button>
                ) : (
                    <LemonButton
                        size="small"
                        data-attr="new-notebook"
                        to={urls.notebook('new')}
                        type="primary"
                        tooltip="New notebook"
                    >
                        New notebook
                    </LemonButton>
                )}
            </Shortcut>
        </AccessControlAction>
    )
}
