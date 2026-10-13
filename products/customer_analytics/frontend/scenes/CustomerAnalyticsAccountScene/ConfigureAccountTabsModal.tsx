import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import {
    isAccountTabVisible,
    listAccountTabs,
    listOrderedAccountTabs,
    reorderAccountTab,
    setAccountTabVisibility,
    type AccountTabDefinition,
} from './accountTabs'
import { accountViewsLogic } from './accountViewsLogic'
import { ConfigureAccountTabsSection } from './ConfigureAccountTabsSection'

interface ConfigureAccountTabsModalProps {
    projectId: number
}

export function ConfigureAccountTabsModal({ projectId }: ConfigureAccountTabsModalProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const { configureOpen, configDraft, configError, configLoading, configSaving, config, views } = useValues(logic)
    const accountViewsEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]
    const { setConfigureOpen, setConfigDraft, saveConfig, openCreateEditor, loadConfig } = useActions(logic)
    const editingDisabledReason = configError
        ? 'Retry loading tab settings before making changes'
        : configLoading || !config
          ? 'Loading tab settings'
          : undefined
    const tabs = listOrderedAccountTabs(listAccountTabs(featureFlags, accountViewsEnabled ? views : []), configDraft)
    const isTabVisible = (tab: AccountTabDefinition): boolean => isAccountTabVisible(tab, configDraft, user?.id)
    const updateVisibility = (tab: AccountTabDefinition, visible: boolean): void =>
        setConfigDraft(setAccountTabVisibility(tabs, tab, configDraft, user?.id, visible))
    const reorderTab = (activeTabId: string, overTabId: string): void =>
        setConfigDraft(reorderAccountTab(tabs, configDraft, user?.id, activeTabId, overTabId))

    return (
        <LemonModal
            isOpen={configureOpen}
            onClose={() => setConfigureOpen(false)}
            title="Configure tabs"
            width={600}
            footer={
                <>
                    {accountViewsEnabled ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={() => {
                                setConfigureOpen(false)
                                openCreateEditor()
                            }}
                            className="mr-auto"
                        >
                            Add view
                        </LemonButton>
                    ) : null}
                    <LemonButton type="secondary" onClick={() => setConfigureOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={configSaving}
                        disabledReason={editingDisabledReason}
                        onClick={saveConfig}
                        data-attr="account-tabs-save"
                    >
                        Save settings
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {configError ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadConfig }}>
                        Couldn't load your saved tab settings. Retry before making changes so they are not overwritten.
                    </LemonBanner>
                ) : null}
                <div className="flex flex-col gap-1">
                    <span className="font-medium">Default tab</span>
                    <LemonSelect
                        value={configDraft.default_tab_id}
                        onChange={(defaultTabId) => setConfigDraft({ ...configDraft, default_tab_id: defaultTabId })}
                        disabledReason={editingDisabledReason}
                        options={tabs.filter(isTabVisible).map((tab) => ({ value: tab.id, label: tab.label }))}
                        placeholder="First available tab"
                    />
                </div>
                <ConfigureAccountTabsSection
                    title="Views"
                    tabs={tabs.filter((tab) => tab.kind === 'view')}
                    disabledReason={editingDisabledReason}
                    isTabVisible={isTabVisible}
                    onVisibilityChange={updateVisibility}
                    onReorder={reorderTab}
                />
                <ConfigureAccountTabsSection
                    title="System tabs"
                    tabs={tabs.filter((tab) => tab.kind === 'system')}
                    disabledReason={editingDisabledReason}
                    isTabVisible={isTabVisible}
                    onVisibilityChange={updateVisibility}
                    onReorder={reorderTab}
                />
            </div>
        </LemonModal>
    )
}
