import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import {
    isAccountTabVisible,
    listAccountTabs,
    listOrderedAccountTabs,
    moveAccountTab,
    setAccountTabVisibility,
} from './accountTabs'
import { accountViewsLogic } from './accountViewsLogic'

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
    const isTabVisible = (tabId: string): boolean => {
        const tab = tabs.find((candidate) => candidate.id === tabId)
        return tab ? isAccountTabVisible(tab, configDraft, user?.id) : false
    }

    const updateVisibility = (tabId: string, visible: boolean): void => {
        const tab = tabs.find((candidate) => candidate.id === tabId)
        if (tab) {
            setConfigDraft(setAccountTabVisibility(tabs, tab, configDraft, user?.id, visible))
        }
    }

    const moveTab = (tabId: string, direction: 'up' | 'down'): void => {
        setConfigDraft(moveAccountTab(tabs, configDraft, user?.id, tabId, direction))
    }

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
                        options={tabs
                            .filter((tab) => isTabVisible(tab.id))
                            .map((tab) => ({ value: tab.id, label: tab.label }))}
                        placeholder="First available tab"
                    />
                </div>
                <div className="flex flex-col gap-2">
                    {tabs.map((tab, index) => (
                        <div key={tab.id} className="flex flex-wrap items-center gap-2 rounded border p-2">
                            <LemonCheckbox
                                checked={isTabVisible(tab.id)}
                                onChange={(visible) => updateVisibility(tab.id, visible)}
                                disabledReason={editingDisabledReason}
                                label={tab.label}
                                className="min-w-40 flex-1"
                            />
                            <LemonTag type="muted">{tab.kind === 'system' ? 'System' : 'View'}</LemonTag>
                            <div className="flex items-center gap-1">
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconChevronDown className="rotate-180" />}
                                    aria-label="Move tab up"
                                    onClick={() => moveTab(tab.id, 'up')}
                                    disabledReason={
                                        editingDisabledReason ?? (index === 0 ? 'Already first' : undefined)
                                    }
                                />
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconChevronDown />}
                                    aria-label="Move tab down"
                                    onClick={() => moveTab(tab.id, 'down')}
                                    disabledReason={
                                        editingDisabledReason ??
                                        (index === tabs.length - 1 ? 'Already last' : undefined)
                                    }
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
