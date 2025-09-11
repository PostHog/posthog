import { actions, connect, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { GroupTypeIndex } from '~/types'

import type { groupViewLogicType } from './groupViewLogicType'

export const groupViewLogic = kea<groupViewLogicType>([
    path(['scenes', 'groups', 'groupView']),
    connect(() => ({
        actions: [
            projectTreeDataLogic,
            ['addShortcutItem'],
            eventUsageLogic,
            ['reportGroupViewSaved'],
            panelLayoutLogic,
            ['setActivePanelIdentifier', 'showLayoutPanel', 'showLayoutNavBar'],
        ],
    })),
    actions(() => ({
        setSaveGroupViewModalOpen: (isOpen: boolean) => ({ isOpen }),
        setGroupViewName: (name: string) => ({ name }),
        saveGroupView: (href: string, groupTypeIndex: GroupTypeIndex) => ({ href, groupTypeIndex }),
    })),
    reducers(() => ({
        saveGroupViewModalOpen: [
            false,
            {
                setSaveGroupViewModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        groupViewName: [
            '',
            {
                setGroupViewName: (_, { name }) => name,
                setSaveGroupViewModalOpen: (state, { isOpen }) => {
                    if (isOpen) {
                        return state
                    }
                    return ''
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        saveGroupView: async ({ href, groupTypeIndex }) => {
            if (!values.groupViewName.trim()) {
                return
            }
            try {
                const currentUrl = new URL(href)
                actions.addShortcutItem({
                    path: values.groupViewName,
                    type: `group_${groupTypeIndex}_view`,
                    href: currentUrl.pathname + currentUrl.search,
                    ref: `groups/${groupTypeIndex}`,
                    created_at: new Date().toISOString(),
                } as FileSystemEntry)
                actions.reportGroupViewSaved(groupTypeIndex, values.groupViewName)
                actions.setSaveGroupViewModalOpen(false)

                // Open the People tab in the left sidebar to show where the saved view is located
                actions.setActivePanelIdentifier('People')
                actions.showLayoutPanel(true)
                actions.showLayoutNavBar(true)

                lemonToast.success('Group view saved')
            } catch (error) {
                posthog.captureException(error)
                lemonToast.error('Failed to save group view')
            }
        },
    })),
])
