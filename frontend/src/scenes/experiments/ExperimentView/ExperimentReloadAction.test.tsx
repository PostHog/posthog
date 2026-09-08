import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ExperimentReloadAction } from './ExperimentReloadAction'

const EXPERIMENT_ID = 45
const END_DATE = '2026-06-10T00:00:00Z'

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

    const renderAction = (
        status: ExperimentStatus,
        dataThrough: string | null,
        coversCurrentMetrics: boolean
    ): void => {
        logic.actions.setExperiment({
            id: EXPERIMENT_ID,
            status,
            start_date: '2026-06-01T00:00:00Z',
            end_date: status === ExperimentStatus.Stopped ? END_DATE : null,
        } as Partial<Experiment>)
        render(
            <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                <ExperimentReloadAction
                    isRefreshing={false}
                    lastRefresh="2026-06-10T00:05:00Z"
                    dataThrough={dataThrough}
                    coversCurrentMetrics={coversCurrentMetrics}
                    onClick={jest.fn()}
                />
            </BindLogic>
        )
    }

    it.each([
        [
            'blocks the reload once a stopped experiment covers its full window',
            ExperimentStatus.Stopped,
            END_DATE,
            true,
            'true',
        ],
        [
            'keeps the reload live when the results stop short of the end date',
            ExperimentStatus.Stopped,
            '2026-06-09T12:00:00Z',
            true,
            'false',
        ],
        [
            'keeps the reload live when the results overshoot a backdated end date',
            ExperimentStatus.Stopped,
            '2026-06-12T00:00:00Z',
            true,
            'false',
        ],
        [
            'keeps the reload live when the run never computed one of the current metrics',
            ExperimentStatus.Stopped,
            END_DATE,
            false,
            'false',
        ],
        [
            'keeps the reload live on a stopped experiment with no results yet',
            ExperimentStatus.Stopped,
            null,
            false,
            'false',
        ],
        ['keeps the reload live while the experiment runs', ExperimentStatus.Running, END_DATE, true, 'false'],
    ])('%s', (_name, status, dataThrough, coversCurrentMetrics, expected) => {
        renderAction(status as ExperimentStatus, dataThrough as string | null, coversCurrentMetrics as boolean)

        expect(screen.getByTestId('refresh-experiment')).toHaveAttribute('aria-disabled', expected)
    })
})
