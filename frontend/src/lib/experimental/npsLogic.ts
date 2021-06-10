import { kea } from 'kea'
import { UserType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import dayjs from 'dayjs'
import posthog from 'posthog-js'
import { npsLogicType } from 'lib/experimental/npsLogicType'

const NPS_APPEAR_TIMEOUT = 10000
const NPS_HIDE_TIMEOUT = 3500
const NPS_LOCALSTORAGE_KEY = 'experimental-nps-v8'

type Step = 0 | 1 | 2 | 3

interface NPSPayload {
    score?: 1 | 3 | 5 // 1 = not disappointed; 3 = somewhat disappointed; 5 = very disappointed
    feedback_score?: string
    feedback_persona?: string
}

export const npsLogic = kea<npsLogicType<NPSPayload, Step, UserType>>({
    selectors: {
        featureFlagEnabled: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.NPS_PROMPT],
        ],
        userIsOldEnough: [
            () => [userLogic.selectors.user],
            (user) => !!user && dayjs(user.date_joined).isBefore(dayjs().add(-15, 'day')),
        ],
        npsPromptEnabled: [
            (s) => [s.featureFlagEnabled, s.userIsOldEnough],
            (featureFlagEnabled, userIsOldEnough) => featureFlagEnabled && userIsOldEnough,
        ],
    },
    actions: {
        show: true,
        hide: true,
        setStep: (step: Step) => ({ step }),
        stepBack: true,
        setPayload: (payload: NPSPayload | null) => ({ payload }),
        submit: true,
    },
    reducers: {
        step: [
            0 as Step,
            {
                setStep: (_, { step }) => step,
                stepBack: (state) => Math.max(state - 1, 0) as Step,
                submit: () => 3,
                // go to step 1 when selecting the score on step 0
                setPayload: (state, { payload }) => (state === 0 && typeof payload?.score !== 'undefined' ? 1 : state),
            },
        ],
        hidden: [true, { show: () => false, hide: () => true }],
        payload: [
            null as NPSPayload | null,
            {
                setPayload: (state, { payload }) => ({ ...state, ...payload }),
            },
        ],
    },
    listeners: ({ values, actions, cache }) => ({
        stepBack: () => {
            if (values.step === 1) {
                actions.setPayload(null)
            }
        },
        submit: () => {
            const payload = values.payload
            let result = 'dismissed'
            if (payload) {
                result = 'partial'
                if (payload.score && payload.feedback_score && payload.feedback_persona) {
                    result = 'completed'
                }
            }
            posthog.capture('nps feedback', { ...payload, result })
            // `nps_2106` is used to identify users who have replied to the NPS survey (via cohorts)
            posthog.people.set({ nps_2106: true })
            localStorage.setItem(NPS_LOCALSTORAGE_KEY, 'true')
            cache.timeout = window.setTimeout(() => actions.hide(), NPS_HIDE_TIMEOUT)
        },
        show: () => {
            posthog.capture('nps modal shown')
        },
    }),
    events: ({ actions, values, cache }) => ({
        afterMount: () => {
            if (values.npsPromptEnabled && !localStorage.getItem(NPS_LOCALSTORAGE_KEY)) {
                cache.timeout = window.setTimeout(() => actions.show(), NPS_APPEAR_TIMEOUT)
            }
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.timeout)
        },
    }),
})
