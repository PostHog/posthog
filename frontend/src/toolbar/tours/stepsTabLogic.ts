import { kea } from 'kea'
import { stepsTabLogicType } from './stepsTabLogicType'
import { TourStepType } from '~/toolbar/types'
import { toursLogic } from '~/toolbar/tours/toursLogic'

export const stepsTabLogic = kea<stepsTabLogicType>({
    actions: {
        setParams: (params: Partial<TourStepType>) => ({ params }),
        submitStep: true,
    },
    reducers: {
        params: [
            {} as Partial<TourStepType>,
            {
                setParams: (state, { params }) => ({ ...state, ...params }),
            },
        ],
    },
    listeners: ({ values }) => ({
        submitStep: () => {
            toursLogic.actions.addStep(values.params as TourStepType)
        },
    }),
})
