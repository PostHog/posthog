import { actions, kea, reducers, path, listeners, connect } from 'kea'
import { Settings } from 'scenes/settings/Settings'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from '@posthog/lemon-ui'

import type { sidePanelSettingsLogicType } from './sidePanelSettingsLogicType'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { SidePanelTab } from '~/types'
import { SettingsLogicProps } from 'scenes/settings/settingsLogic'

export const sidePanelSettingsLogic = kea<sidePanelSettingsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSettingsLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    }),

    actions({
        openSettingsPanel: (settingsLogicProps: SettingsLogicProps) => ({
            settingsLogicProps,
        }),
        setSettings: (settingsLogicProps: SettingsLogicProps) => ({
            settingsLogicProps,
        }),
    }),

    reducers(() => ({
        settings: [
            {} as SettingsLogicProps,
            { persist: true },
            {
                openSettingsPanel: (_, { settingsLogicProps }) => {
                    return settingsLogicProps
                },
                setSettings: (_, { settingsLogicProps }) => {
                    return settingsLogicProps
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        openSettingsPanel: ({ settingsLogicProps }) => {
            if (!values.featureFlags[FEATURE_FLAGS.POSTHOG_3000]) {
                LemonDialog.open({
                    title: 'Settings',
                    content: <Settings {...settingsLogicProps} hideSections logicKey="modal" />,
                    width: 600,
                    primaryButton: {
                        children: 'Done',
                    },
                })
                return
            }

            actions.openSidePanel(SidePanelTab.Settings)
        },
    })),
])
