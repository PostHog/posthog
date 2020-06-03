import { kea } from 'kea'
import api from 'lib/api'

export const TourType = {
    ACTION: 'Action',
    TRENDS: 'Trend',
    FUNNEL: 'Funnel',
}

export const onboardingLogic = kea({
    actions: () => ({
        setTourFinish: true,
        setTourActive: true,
        setTourStep: step => ({ step }),
        setTourType: type => ({ type }),
        updateOnboardingStep: index => ({ index }),
        updateOnboardingInitial: initial => ({ initial }),
    }),
    reducers: ({ actions }) => ({
        tourActive: [
            false,
            {
                [actions.setTourActive]: () => true,
                [actions.setTourFinish]: () => false,
            },
        ],
        tourType: [
            TourType.FUNNEL,
            {
                [actions.setTourType]: (_, { type }) => type,
            },
        ],
        tourStep: [
            0,
            {
                [actions.setTourStep]: (_, { step }) => step,
            },
        ],
        localChecked: [
            Object.entries(TourType).map(_ => false),
            {
                [actions.updateOnboardingStep]: (state, { index }) => {
                    if (index > state.length) return state
                    state[index] = true
                    console.log(state)
                    return state
                },
            },
        ],
    }),
    selectors: ({ selectors, props }) => ({
        checked: [
            () => [selectors.localChecked],
            localChecked => {
                return localChecked.map((val, index) => val || props.user.onboarding.steps[index])
            },
        ],
    }),
    listeners: ({ props, actions }) => ({
        [actions.updateOnboardingStep]: ({ index }) => {
            const user = props.user
            if (index >= user.onboarding.steps.length) return
            if (!user.onboarding.steps[index]) {
                api.update('api/user', {
                    onboarding: {
                        ...user.onboarding,
                        steps: {
                            ...user.onboarding.steps,
                            [index]: true,
                        },
                    },
                })
            }
        },
        [actions.updateOnboardingInitial]: ({ initial }) => {
            const user = props.user
            api.update('api/user', { onboarding: { ...user.onboarding, initial } })
        },
    }),
})
