import { actions, kea, reducers, path, listeners, connect } from 'kea'
import { SidePanelTab, sidePanelLogic } from '../sidePanelLogic'
import { SettingsLogicProps } from 'scenes/settings/settingsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from '@posthog/lemon-ui'
import { SettingsRenderer } from 'scenes/settings/SettingsRenderer'

import type { sidePanelSettingsLogicType } from './sidePanelSettingsLogicType'

export const sidePanelSettingsLogic = kea<sidePanelSettingsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSettingsLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [sidePanelLogic, ['openSidePanel', 'closeSidePanel']],
    }),

    actions({
        openSettingsPanel: (settingsLogicProps: SettingsLogicProps) => ({
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
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        openSettingsPanel: ({ settingsLogicProps }) => {
            if (!values.featureFlags[FEATURE_FLAGS.POSTHOG_3000]) {
                LemonDialog.open({
                    title: 'Settings',
                    content: <SettingsRenderer {...settingsLogicProps} />,
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
