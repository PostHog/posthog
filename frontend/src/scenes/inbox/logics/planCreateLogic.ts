import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { signalsPlansCreate } from 'products/signals/frontend/generated/api'

import type { planCreateLogicType } from './planCreateLogicType'

/**
 * The "New plan" flow: a modal asking for a brief initial description, then a create call that
 * lands the user on the new plan's draft view (live overview + planning conversation).
 */
export const planCreateLogic = kea<planCreateLogicType>([
    path(['scenes', 'inbox', 'logics', 'planCreateLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        openNewPlanModal: true,
        closeNewPlanModal: true,
        setDescriptionDraft: (draft: string) => ({ draft }),
        createPlan: true,
        setCreating: (creating: boolean) => ({ creating }),
    }),

    reducers({
        newPlanModalOpen: [
            false,
            {
                openNewPlanModal: () => true,
                closeNewPlanModal: () => false,
            },
        ],
        descriptionDraft: [
            '',
            {
                setDescriptionDraft: (_, { draft }) => draft,
                closeNewPlanModal: () => '',
            },
        ],
        creating: [
            false,
            {
                setCreating: (_, { creating }) => creating,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        createPlan: async () => {
            const description = values.descriptionDraft.trim()
            if (!description) {
                lemonToast.error('Describe the idea first — a sentence is enough')
                return
            }
            if (values.creating) {
                return
            }
            actions.setCreating(true)
            try {
                const created = await signalsPlansCreate(String(values.currentProjectId), {
                    initial_description: description,
                })
                actions.closeNewPlanModal()
                router.actions.push(urls.inboxReport('plan', created.report_id))
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to create plan')
            } finally {
                actions.setCreating(false)
            }
        },
    })),
])
