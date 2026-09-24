import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { listAccountTabs, listOrderedAccountTabs } from './accountTabs'
import { accountViewsLogic } from './accountViewsLogic'

interface ConfigureAccountTabsModalProps {
    projectId: number
}

export function ConfigureAccountTabsModal({ projectId }: ConfigureAccountTabsModalProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const { configureOpen, configDraft, configSaving, views } = useValues(logic)
    const { setConfigureOpen, setConfigDraft, saveConfig, openCreateEditor } = useActions(logic)
    const tabs = listOrderedAccountTabs(listAccountTabs(featureFlags, views), configDraft)
    const hidden = new Set(configDraft.hidden_tab_ids)

    const isTabVisible = (tabId: string): boolean => {
        const tab = tabs.find((candidate) => candidate.id === tabId)
        const unselectedTeamView =
            tab?.view?.visibility === 'team' &&
            tab.view.created_by !== user?.id &&
            !configDraft.ordered_tab_ids.includes(tabId)
        return !hidden.has(tabId) && !unselectedTeamView
    }

    const updateVisibility = (tabId: string, visible: boolean): void => {
        setConfigDraft({
            ...configDraft,
            ordered_tab_ids:
                visible && !configDraft.ordered_tab_ids.includes(tabId)
                    ? [...configDraft.ordered_tab_ids, tabId]
                    : configDraft.ordered_tab_ids,
            hidden_tab_ids: visible
                ? configDraft.hidden_tab_ids.filter((id) => id !== tabId)
                : [...new Set([...configDraft.hidden_tab_ids, tabId])],
            default_tab_id: !visible && configDraft.default_tab_id === tabId ? null : configDraft.default_tab_id,
        })
    }

    const moveTab = (tabId: string, direction: 'up' | 'down'): void => {
        const orderedTabIds = tabs.map((tab) => tab.id)
        const index = orderedTabIds.indexOf(tabId)
        const nextIndex = direction === 'up' ? index - 1 : index + 1
        if (index < 0 || nextIndex < 0 || nextIndex >= orderedTabIds.length) {
            return
        }
        ;[orderedTabIds[index], orderedTabIds[nextIndex]] = [orderedTabIds[nextIndex], orderedTabIds[index]]
        setConfigDraft({ ...configDraft, ordered_tab_ids: orderedTabIds })
    }

    return (
        <LemonModal
            isOpen={configureOpen}
            onClose={() => setConfigureOpen(false)}
            title="Configure tabs"
            width={600}
            footer={
                <>
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
                    <LemonButton type="secondary" onClick={() => setConfigureOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={configSaving}
                        onClick={saveConfig}
                        data-attr="account-tabs-save"
                    >
                        Save settings
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <span className="font-medium">Default tab</span>
                    <LemonSelect
                        value={configDraft.default_tab_id}
                        onChange={(defaultTabId) => setConfigDraft({ ...configDraft, default_tab_id: defaultTabId })}
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
                                    disabledReason={index === 0 ? 'Already first' : undefined}
                                />
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconChevronDown />}
                                    aria-label="Move tab down"
                                    onClick={() => moveTab(tab.id, 'down')}
                                    disabledReason={index === tabs.length - 1 ? 'Already last' : undefined}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
