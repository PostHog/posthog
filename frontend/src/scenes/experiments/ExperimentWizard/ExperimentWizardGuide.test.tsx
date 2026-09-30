import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { type Experiment, SidePanelTab } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { createExperimentLogic } from '../ExperimentForm/createExperimentLogic'
import { ExperimentWizardGuide } from './ExperimentWizardGuide'
import { experimentWizardLogic } from './experimentWizardLogic'

const SAVED_EXPERIMENT = {
    ...NEW_EXPERIMENT,
    id: 42,
    name: 'Checkout flow',
    feature_flag_key: 'checkout-flow',
    feature_flag: {
        id: 7,
        key: 'checkout-flow',
        filters: {
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
    },
} as unknown as Experiment

describe('ExperimentWizardGuide', () => {
    let wizardLogic: ReturnType<typeof experimentWizardLogic.build>

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/': () => [200, { results: [], count: 0 }],
                '/api/projects/:team_id/experiments': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests()
        sidePanelLogic.mount()
        createExperimentLogic().mount()
        wizardLogic = experimentWizardLogic()
        wizardLogic.mount()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it("sends a question about adding the saved experiment's code on the implementation step", async () => {
        const openSidePanel = jest.spyOn(sidePanelLogic.actions, 'openSidePanel')
        createExperimentLogic().actions.setExperiment(SAVED_EXPERIMENT)
        wizardLogic.actions._applyStep('implementation', 'save')
        render(<ExperimentWizardGuide />)

        expect(screen.getByText('Need help with the code? PostHog AI can explain how to add it.')).toBeInTheDocument()
        await userEvent.click(screen.getByText('Ask AI'))

        expect(openSidePanel).toHaveBeenCalledWith(
            SidePanelTab.Max,
            '!How do I add the "Checkout flow" experiment to my code? Its feature flag key is checkout-flow, with the variants control and test.'
        )
    })

    it('opens with the new experiment prompt, unsent, on the first step', async () => {
        const openSidePanel = jest.spyOn(sidePanelLogic.actions, 'openSidePanel')
        render(<ExperimentWizardGuide />)

        expect(screen.getByText('Rather describe it? PostHog AI can set it up for you.')).toBeInTheDocument()
        await userEvent.click(screen.getByText('Ask AI'))

        expect(openSidePanel).toHaveBeenCalledWith(SidePanelTab.Max, 'Create an experiment for ')
    })
})
