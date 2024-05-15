import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, ReferralProgram } from '~/types'

import type { referralProgramLogicType } from './referralProgramLogicType'
import { referralsSceneLogic } from './referralsSceneLogic'

export const NEW_REFERRAL_PROGRAM: ReferralProgram = {
    title: '',
    description: '',
    id: '',
    short_id: '',
}

export interface ReferralProgramLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const referralProgramLogic = kea<referralProgramLogicType>([
    path(['scenes', 'referrals', 'referralProgramLogic']),
    props({} as ReferralProgramLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], referralsSceneLogic, ['referrals']],
        actions: [referralsSceneLogic, ['loadReferrals', 'loadReferralsSuccess']],
    })),
    actions({
        setReferralProgramMissing: true,
        toggleImplementOptInInstructionsModal: true,
        editProgram: (editing: boolean) => ({ editing }),
    }),
    loaders(({ props, actions }) => ({
        referralProgram: {
            loadReferralProgram: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const response = await api.referralPrograms.get(props.id)
                        return response
                    } catch (error: any) {
                        actions.setReferralProgramMissing()
                        throw error
                    }
                }
                return NEW_REFERRAL_PROGRAM
            },
            saveReferralProgram: async (updatedReferralProgram: Partial<ReferralProgram>) => {
                let result: ReferralProgram
                if (props.id === 'new') {
                    result = await api.referralPrograms.create(updatedReferralProgram as ReferralProgram)
                    router.actions.replace(urls.referralProgram(result.short_id))
                } else {
                    result = await api.referralPrograms.update(props.id, updatedReferralProgram as ReferralProgram)
                }
                return result
            },
        },
    })),
    forms(({ actions }) => ({
        referralProgram: {
            defaults: { ...NEW_REFERRAL_PROGRAM },
            errors: (payload) => ({
                title: !payload.title ? 'Program name must be set' : undefined,
            }),
            submit: async (payload) => {
                actions.saveReferralProgram(payload)
            },
        },
    })),
    reducers({
        referralProgramMissing: [
            false,
            {
                setReferralProgramMissing: () => true,
            },
        ],
        isEditingProgram: [
            false,
            {
                editProgram: (_, { editing }) => editing,
            },
        ],
    }),
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
        breadcrumbs: [
            (s) => [s.referralProgram],
            (referralProgram: ReferralProgram): Breadcrumb[] => [
                {
                    key: Scene.Referrals,
                    name: 'Referrals',
                    path: urls.referralPrograms(),
                },
                {
                    key: [Scene.Referrals, referralProgram.id || 'new'],
                    name: referralProgram.title,
                },
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        saveReferralProgramSuccess: ({ referralProgram }) => {
            lemonToast.success('Referral program saved')
            actions.loadReferrals()
            referralProgram.id && router.actions.replace(urls.referralProgram(referralProgram.id))
            actions.editProgram(false)
        },
        deleteReferralProgram: async ({ referralProgramId }) => {
            try {
                await api.referralPrograms.delete(referralProgramId)
                lemonToast.info('Referral program deleted.')
                actions.loadReferralsSuccess(values.referrals.filter((program) => program.id !== referralProgramId))
                router.actions.push(urls.referralPrograms())
            } catch (e) {
                lemonToast.error(`Error deleting referral program: ${e}`)
            }
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.referralProgram(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadReferralProgram()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadReferralProgram()
        }
    }),
])
