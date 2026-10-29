import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { experimentLogic } from '../experimentLogic'
import { DeletedFlagBanner } from './DeletedFlagBanner'

const EXPERIMENT_ID = 7
const FLAG_ID = 11

const deletedFlag = {
    id: FLAG_ID,
    team_id: 1,
    key: `checkout-flag:deleted:${FLAG_ID}`,
    name: '',
    filters: { groups: [] },
    deleted: true,
    active: true,
    ensure_experience_continuity: false,
}

function draftExperiment(featureFlag: Record<string, unknown> = deletedFlag): Experiment {
    return {
        ...NEW_EXPERIMENT,
        id: EXPERIMENT_ID,
        feature_flag_key: 'checkout-flag',
        feature_flag: featureFlag,
    } as unknown as Experiment
}

const deletion = {
    id: '1',
    activity: 'deleted',
    scope: 'FeatureFlag',
    item_id: String(FLAG_ID),
    user: { first_name: 'Tue', email: 'tue@example.com' },
    created_at: dayjs().subtract(3, 'day').toISOString(),
    is_system: false,
    was_impersonated: false,
    client: 'mcp',
}

describe('DeletedFlagBanner', () => {
    let logic: ReturnType<typeof experimentLogic.build>
    let restoreBodies: unknown[]

    function renderBanner(experiment: Experiment): void {
        logic.actions.setExperiment(experiment)
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <DeletedFlagBanner />
                </BindLogic>
            </Provider>
        )
    }

    beforeEach(() => {
        restoreBodies = []
        const emptyList = { count: 0, next: null, previous: null, results: [] }
        useMocks({
            get: {
                '/api/projects/:team/experiments': emptyList,
                '/api/projects/:team/experiment_holdouts': emptyList,
                '/api/projects/:team/experiment_saved_metrics': emptyList,
                '/api/projects/:team/experiments/:id': () => [
                    200,
                    draftExperiment({ ...deletedFlag, key: 'checkout-flag', deleted: false }),
                ],
                '/api/projects/:team/feature_flags/:id/activity': {
                    results: [deletion],
                    next: null,
                    previous: null,
                    total_count: 1,
                },
            },
            patch: {
                '/api/projects/:team/feature_flags/:id': async ({ request }) => {
                    restoreBodies.push(await request.json())
                    return [200, { ...deletedFlag, key: 'checkout-flag', deleted: false }]
                },
            },
        })
        initKeaTests()
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('names who deleted the flag, and through which client', async () => {
        renderBanner(draftExperiment())

        expect(await screen.findByText(/Tue deleted/)).toBeInTheDocument()
        expect(screen.getByText(/via MCP/)).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'checkout-flag' })).toHaveAttribute(
            'href',
            expect.stringContaining(`/feature-flags/${FLAG_ID}`)
        )
        expect(screen.getByText(/can't launch until the flag is restored/)).toBeInTheDocument()
    })

    it('restores the flag and reloads the experiment', async () => {
        renderBanner(draftExperiment())

        // LemonBanner renders its action twice, once per layout.
        await userEvent.click(screen.getAllByRole('button', { name: 'Restore flag' })[0])

        await waitFor(() => expect(restoreBodies).toEqual([{ deleted: false }]))
        await waitFor(() => expect(screen.queryByText(/feature flag is deleted/)).not.toBeInTheDocument())
    })

    it('still explains the delete when the activity log cannot be read', async () => {
        useMocks({ get: { '/api/projects/:team/feature_flags/:id/activity': () => [500, { detail: 'Server error' }] } })
        renderBanner(draftExperiment())

        expect(await screen.findByText(/The feature flag/)).toBeInTheDocument()
        expect(screen.getByText(/was deleted/)).toBeInTheDocument()
        expect(screen.getAllByRole('button', { name: 'Restore flag' }).length).toBeGreaterThan(0)
    })

    it('offers no restore for a flag on the new config format', async () => {
        renderBanner(draftExperiment({ ...deletedFlag, filters: { version: 2, rules: [] } }))

        expect(await screen.findByText(/Restoring is not available for this flag yet/)).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Restore flag' })).not.toBeInTheDocument()
    })

    it.each([
        {
            state: 'a running experiment',
            experiment: { start_date: dayjs().subtract(3, 'day').toISOString(), status: ExperimentStatus.Running },
        },
        {
            state: 'an ended experiment',
            experiment: {
                start_date: dayjs().subtract(10, 'day').toISOString(),
                end_date: dayjs().subtract(3, 'day').toISOString(),
                status: ExperimentStatus.Stopped,
            },
        },
    ])('stays hidden for $state', ({ experiment }) => {
        renderBanner({ ...draftExperiment(), ...experiment } as Experiment)

        expect(screen.queryByText(/feature flag is deleted/)).not.toBeInTheDocument()
    })

    it('stays hidden when the flag is not deleted', () => {
        renderBanner(draftExperiment({ ...deletedFlag, deleted: false }))

        expect(screen.queryByText(/feature flag is deleted/)).not.toBeInTheDocument()
    })
})
