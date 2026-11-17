import { useActions, useValues } from 'kea'

import { IconEye, IconGear, IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { useTodayPeoplePinAction } from '~/layout/today/useTodayPeoplePinAction'

import { AccountPresence } from './AccountPresence'
import { accountViewsLogic } from './accountViewsLogic'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

const RESOURCE_TYPE = 'customer-analytics-account'

export function CustomerAnalyticsAccountSceneMenuBar({ projectId }: { projectId: number | null }): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    // accountViewsLogic is keyed by project, so the view actions only exist once there is one.
    return projectId ? (
        <CustomerAnalyticsAccountSceneMenuBarWithViews projectId={projectId} />
    ) : (
        <CustomerAnalyticsAccountSceneMenuBarInner viewActions={[]} />
    )
}

function CustomerAnalyticsAccountSceneMenuBarWithViews({ projectId }: { projectId: number }): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { accountDetailTabs, config, configError, configLoading } = useValues(logic)
    const { openConfigure, openCreateEditor } = useActions(logic)
    const configureDisabledReason = configLoading || (!config && !configError) ? 'Loading tab settings' : undefined
    const configure = (): void => openConfigure(config && !configError ? accountDetailTabs : null)

    const viewActions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-view`,
            label: 'New view',
            icon: <IconPlus />,
            opensFloatingUi: true,
            onSelect: openCreateEditor,
            pinned: { order: 1, variant: 'primary', dataAttr: 'account-detail-add-view' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-configure-tabs`,
            label: 'Configure tabs',
            icon: <IconGear />,
            opensFloatingUi: true,
            disabledReason: configureDisabledReason,
            onSelect: configure,
            pinned: { order: 1, variant: 'secondary', dataAttr: 'account-detail-configure-tabs' },
        },
    ]

    return <CustomerAnalyticsAccountSceneMenuBarInner viewActions={viewActions} />
}

function CustomerAnalyticsAccountSceneMenuBarInner({ viewActions }: { viewActions: SceneAction[] }): JSX.Element {
    const { accountPresenceViewers } = useValues(customerAnalyticsAccountSceneLogic)
    const pinActions = useTodayPeoplePinAction()

    const actions: SceneAction[] = [
        ...viewActions,
        ...pinActions,
        ...(accountPresenceViewers.length
            ? ([
                  {
                      group: 'metadata',
                      type: 'panel',
                      id: `${RESOURCE_TYPE}-menubar-viewers`,
                      label: 'Viewing now',
                      icon: <IconEye />,
                      render: () => <AccountPresence />,
                      pinned: { order: 1, variant: 'icon', render: () => <AccountPresence /> },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
