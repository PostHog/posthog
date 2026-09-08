import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ExperimentReloadAction } from './ExperimentReloadAction'

const EXPERIMENT_ID = 45
const LAST_REFRESH = '2026-06-10T00:05:00Z'

describe('ExperimentReloadAction', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team/experiments/:id': () => [200, {}] } })
        initKeaTests()
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    const renderAction = (status: ExperimentStatus, lastRefresh: string | null): void => {
        logic.actions.setExperiment({
            id: EXPERIMENT_ID,
            status,
            start_date: '2026-06-01T00:00:00Z',
            end_date: status === ExperimentStatus.Stopped ? '2026-06-10T00:00:00Z' : null,
        } as Partial<Experiment>)
        render(
            <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                <ExperimentReloadAction isRefreshing={false} lastRefresh={lastRefresh} onClick={jest.fn()} />
            </BindLogic>
        )
    }

    it.each([
        ['blocks the reload once a stopped experiment has results', ExperimentStatus.Stopped, LAST_REFRESH, 'true'],
        ['keeps the reload live on a stopped experiment with no results yet', ExperimentStatus.Stopped, null, 'false'],
        ['keeps the reload live while the experiment runs', ExperimentStatus.Running, LAST_REFRESH, 'false'],
    ])('%s', (_name, status, lastRefresh, expected) => {
        renderAction(status as ExperimentStatus, lastRefresh as string | null)

        expect(screen.getByTestId('refresh-experiment')).toHaveAttribute('aria-disabled', expected)
    })
})
