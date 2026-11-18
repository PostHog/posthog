import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { accountViewsLogic } from './accountViewsLogic'

interface QuillAccountDetailActionsProps {
    projectId: number
}

export function QuillAccountDetailActions({ projectId }: QuillAccountDetailActionsProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { accountDetailTabs, config, configError, configLoading } = useValues(logic)
    const { openConfigure, openCreateEditor } = useActions(logic)

    return (
        <>
            <Button
                variant="outline"
                data-attr="account-detail-configure-tabs"
                disabledReason={configLoading || (!config && !configError) ? 'Loading tab settings' : undefined}
                onClick={() => openConfigure(config && !configError ? accountDetailTabs : null)}
            >
                <IconGear />
                Configure tabs
            </Button>
            <Button variant="primary" data-attr="account-detail-add-view" onClick={openCreateEditor}>
                <IconPlus />
                New view
            </Button>
        </>
    )
}
