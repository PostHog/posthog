import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'

const CHANGED_AT = '2024-03-05T12:00:00Z'

const RUNNING_EXPERIMENT = {
    id: 1,
    name: 'Split changed',
    start_date: '2024-03-01T00:00:00Z',
    end_date: null,
    feature_flag: {
        id: 7,
        key: 'split-flag',
        active: true,
        filters: {
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
    },
} as unknown as Experiment

describe('ExperimentWarningBanner', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = experimentLogic()
        logic.mount()
    })

    it('says nothing when the split has not changed since launch', () => {
        logic.actions.setExperiment(RUNNING_EXPERIMENT)

        render(<ExperimentWarningBanner />)

        expect(screen.queryByText(/variant split changed/i)).not.toBeInTheDocument()
    })

    it('warns and offers to measure from the change when the split changed mid-run', async () => {
        const changeExperimentStartDate = jest.spyOn(logic.actions, 'changeExperimentStartDate')
        logic.actions.setExperiment({ ...RUNNING_EXPERIMENT, variant_split_changed_at: CHANGED_AT })

        render(<ExperimentWarningBanner />)

        expect(screen.getByText(/variant split changed while the experiment was running/i)).toBeInTheDocument()
        await userEvent.click(screen.getByRole('button', { name: /move start date to the change/i }))

        expect(changeExperimentStartDate).toHaveBeenCalledWith(CHANGED_AT)
    })
})
