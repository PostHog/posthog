import { kea } from 'kea'

export const onboardingLogic = kea({
    actions: () => ({
        setTourActive: true,
        setTourFinish: true,
    }),
    reducers: ({ actions }) => ({
        tourActive: [
            false,
            {
                [actions.setTourActive]: () => true,
                [actions.setTourFinish]: () => false,
            },
        ],
        tourType: [null],
    }),
})
