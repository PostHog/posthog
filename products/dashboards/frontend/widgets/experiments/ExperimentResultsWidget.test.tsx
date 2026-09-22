import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ExperimentResultsWidget } from './ExperimentResultsWidget'

describe('ExperimentResultsWidget', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM })
        teamLogic.mount()
    })

    const noExperimentSelected = { needsConfiguration: true, hasExperiments: true, metrics: [] }

    it('lets an editor pick an experiment inline when none is selected', () => {
        const { container } = render(
            <ExperimentResultsWidget
                tileId={1}
                config={{}}
                loading={false}
                result={noExperimentSelected}
                onUpdateConfig={jest.fn()}
            />
        )

        expect(screen.getByText('No experiment selected')).toBeInTheDocument()
        expect(
            container.querySelector('[data-attr="experiment-results-widget-empty-state-select"]')
        ).toBeInTheDocument()
    })

    it('does not expose the inline picker on a read-only (shared) tile', () => {
        const { container } = render(
            <ExperimentResultsWidget tileId={1} config={{}} loading={false} result={noExperimentSelected} />
        )

        expect(screen.getByText('No experiment has been selected for this tile yet.')).toBeInTheDocument()
        expect(
            container.querySelector('[data-attr="experiment-results-widget-empty-state-select"]')
        ).not.toBeInTheDocument()
    })

    it('shows an error instead of clearing a selected experiment when a run fails', () => {
        render(
            <ExperimentResultsWidget
                tileId={1}
                config={{ experimentId: 123 }}
                error="Could not load experiment results."
                loading={false}
                result={null}
                onRefresh={jest.fn()}
            />
        )

        expect(screen.getByText("Couldn't load experiment results. Try again.")).toBeInTheDocument()
        expect(screen.queryByText('No experiment selected')).not.toBeInTheDocument()
    })
})
