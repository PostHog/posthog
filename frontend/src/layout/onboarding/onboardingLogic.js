import { kea } from 'kea'

export const TourType = {
    ACTION: 'action',
    TRENDS: 'trends',
    FUNNEL: 'funnel',
}

export const onboardingLogic = kea({
    actions: () => ({
        setTourFinish: true,
        setTourActive: true,
        setTourStep: step => ({ step }),
        setTourType: type => ({ type }),
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
    }),
})
