import { useActions } from 'kea'
import { router } from 'kea-router'
import { useContext } from 'react'

import { IconExternal, IconGear, IconSidePanel } from '@posthog/icons'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { SceneContentContext } from '../components/SceneContent'
import { getSceneSettingsUrl } from '../components/sceneSettingsUrl'
import type { SceneAction } from './sceneActionModel'

/** The Help menu every scene ends with. Scenes never declare their own. */
export function useSceneHelpActions(): SceneAction[] {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { productKey } = useContext(SceneContentContext)
    const settingsUrl = getSceneSettingsUrl(productKey)

    return [
        ...(settingsUrl
            ? [
                  {
                      group: 'help',
                      section: 'settings',
                      // pinned: data-attr values are wire strings
                      id: 'scene-menu-bar-settings',
                      label: 'Settings',
                      icon: <IconGear />,
                      onSelect: () => router.actions.push(settingsUrl),
                  } satisfies SceneAction,
              ]
            : []),
        {
            group: 'help',
            id: 'scene-menu-bar-docs',
            label: 'Docs',
            icon: <IconExternal />,
            onSelect: () => window.open('https://posthog.com/docs', '_blank', 'noopener'),
        },
        {
            group: 'help',
            id: 'scene-menu-bar-support',
            label: 'Support',
            icon: <IconSidePanel />,
            opensFloatingUi: true,
            onSelect: () => openSidePanel(SidePanelTab.Support),
        },
    ]
}
