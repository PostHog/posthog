import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'
import type { groupViewLogicType } from './groupViewLogicType'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { GroupTypeIndex } from '~/types'

export const groupViewLogic = kea<groupViewLogicType>([
    path(['scenes', 'groups', 'groupView']),
    connect(() => ({
        actions: [projectTreeDataLogic, ['addShortcutItem'], eventUsageLogic, ['reportGroupViewSaved']],
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
                    id: '',
                    path: values.groupViewName,
                    type: `group_${groupTypeIndex}_view`,
                    href: currentUrl.pathname + currentUrl.search,
                    ref: `groups/${groupTypeIndex}`,
                    created_at: new Date().toISOString(),
                })
                actions.reportGroupViewSaved(groupTypeIndex, values.groupViewName)
                actions.setSaveGroupViewModalOpen(false)
                lemonToast.success('Filter view saved')
            } catch (error) {
                posthog.captureException(error)
                lemonToast.error('Failed to save filter shortcut')
            }
        },
    })),
])
