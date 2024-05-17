import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, ReferralIdentity, ReferralProgram } from '~/types'

import { referralProgramLogic } from './referralProgramLogic'
import { referralsSceneLogic } from './referralsSceneLogic'
import type { referrerLogicType } from './referrerLogicType'

export const NEW_REFERRAL_PROGRAM: ReferralIdentity = {
    user_id: '',
    code: '',
    created_at: '',
    total_redemptions: 0,
    total_points: 0,
}

export interface ReferrerLogicProps {
    /** Either a UUID or "new". */
    id: string
    program_short_id: string
}

export const referrerLogic = kea<referrerLogicType>([
    path(['scenes', 'referrals', 'referrerLogic']),
    props({ id: '', program_short_id: '' } as ReferrerLogicProps),
    key(({ id, program_short_id }) => `program-${program_short_id}-user_id-${id}`),
    connect((props: ReferrerLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            referralsSceneLogic,
            ['referrals'],
            referralProgramLogic({ id: props.program_short_id }),
            ['referralProgram'],
        ],
        actions: [referralsSceneLogic, ['loadReferrals', 'loadReferralsSuccess']],
    })),
    actions({
        setReferrerMissing: true,
        // editReferrer: (editing: boolean) => ({ editing }),
    }),
    loaders(({ props, actions }) => ({
        referrer: {
            loadReferrer: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const response = await api.referralProgramReferrers.get(props.program_short_id, props.id)
                        return response
                    } catch (error: any) {
                        actions.setReferrerMissing()
                        throw error
                    }
                }
                return NEW_REFERRAL_PROGRAM
            },
            // saveReferrer: async (updatedReferrer: Partial<ReferralIdentity>) => {
            //     let result: ReferralIdentity
            //     if (props.id === 'new') {
            //         result = await api.referralProgramReferrers.create(updatedReferrer)
            //         router.actions.replace(urls.referrer(props.program_short_id, result.short_id))
            //     } else {
            //         result = await api.referralProgramReferrers.update(props.id, updatedReferrer)
            //     }
            //     return result
            // },
        },
    })),
    forms(({ actions }) => ({
        referrer: {
            defaults: { ...NEW_REFERRAL_PROGRAM },
            errors: (payload) => ({
                title: !payload.title ? 'Program name must be set' : undefined,
            }),
            submit: async (payload) => {
                actions.saveReferrer(payload)
            },
        },
    })),
    reducers({
        referrerMissing: [
            false,
            {
                setReferrerMissing: () => true,
            },
        ],
        isEditingReferrer: [
            false,
            {
                editReferrer: (_, { editing }) => editing,
            },
        ],
    }),
    selectors({
        // mode: [(_, p) => [p.userId], (userId = ''\): 'view' | 'edit' => (userId === 'new' ? 'edit' : 'view')],
        breadcrumbs: [
            (s) => [s.referrer, s.referralProgram],
            (referrer: ReferralIdentity, referralProgram: ReferralProgram): Breadcrumb[] => [
                {
                    key: Scene.Referrals,
                    name: 'Referrals',
                    path: urls.referralPrograms(),
                },
                {
                    key: Scene.ReferralProgram,
                    name: referralProgram.title,
                    path: urls.referralProgram(referralProgram.short_id),
                },
                {
                    key: [Scene.Referrals, referrer.user_id || 'new'],
                    name: referrer.user_id,
                },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        saveReferrerSuccess: ({ referrer }) => {
            lemonToast.success('Referral program saved')
            actions.loadReferrals()
            referrer.short_id && router.actions.replace(urls.referrer(referrer.short_id))
            actions.editReferrer(false)
        },
        // deleteReferrer: async ({ referrerId }) => {
        //     try {
        //         await api.referrers.delete(referrerId)
        //         lemonToast.info('Referral program deleted.')
        //         actions.loadReferralsSuccess(values.referrals.filter((program) => program.short_id !== referrerId))
        //         router.actions.push(urls.referrers())
        //     } catch (e) {
        //         lemonToast.error(`Error deleting referral program: ${e}`)
        //     }
        // },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.referrer(props.program_short_id, props.userId ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadReferrer()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadReferrer()
        }
    }),
])
