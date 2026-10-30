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
import { deletedFlagBannerLogic } from './deletedFlagBannerLogic'

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

// The flag API's copy of the flag. Unlike the experiment's copy, it says whether the viewer can edit the flag.
const flagFromFlagApi = { ...deletedFlag, archived: false, can_edit: true }

function draftExperiment(featureFlag: Record<string, unknown> = deletedFlag): Experiment {
    return {
        ...NEW_EXPERIMENT,
        id: EXPERIMENT_ID,
        feature_flag_key: 'checkout-flag',
        feature_flag: featureFlag,
    } as unknown as Experiment
}

// LemonBanner renders its action twice, once per layout.
function restoreButtons(): NodeListOf<HTMLButtonElement> {
    return document.querySelectorAll<HTMLButtonElement>('[data-attr="experiment-restore-deleted-flag"]')
}

const deletion = {
    id: '1',
    activity: 'deleted',
    scope: 'FeatureFlag',
    item_id: String(FLAG_ID),
    user: { first_name: 'Max', last_name: 'Smith', email: 'max@example.com' },
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
                '/api/projects/:team/feature_flags/:id': flagFromFlagApi,
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

    it.each([
        { who: 'a member by full name', entry: {}, name: 'Max Smith' },
        {
            who: 'support while impersonating',
            entry: { was_impersonated: true },
            name: 'PostHog Support (as Max Smith)',
        },
        { who: 'the system', entry: { is_system: true, user: null }, name: 'PostHog' },
    ])('names $who as the activity log does', async ({ entry, name }) => {
        useMocks({
            get: {
                '/api/projects/:team/feature_flags/:id/activity': {
                    results: [{ ...deletion, ...entry }],
                    next: null,
                    previous: null,
                    total_count: 1,
                },
            },
        })
        renderBanner(draftExperiment())

        expect(await screen.findByText((text) => text.startsWith(`${name} deleted`))).toBeInTheDocument()
    })

    it('links the flag, and names the client that deleted it', async () => {
        renderBanner(draftExperiment())

        expect(await screen.findByText(/via MCP/)).toBeInTheDocument()
        expect(screen.getByText('checkout-flag').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(`/feature-flags/${FLAG_ID}`)
        )
        expect(screen.getByText(/can't launch until the flag is restored/)).toBeInTheDocument()
    })

    it('restores the flag and reloads the experiment', async () => {
        renderBanner(draftExperiment())

        await screen.findByText(/feature flag is deleted/)
        await userEvent.click(restoreButtons()[0])

        await waitFor(() => expect(restoreBodies).toEqual([{ deleted: false }]))
        await waitFor(() => expect(screen.queryByText(/feature flag is deleted/)).not.toBeInTheDocument())
    })

    it('still explains the delete when the activity log cannot be read', async () => {
        useMocks({ get: { '/api/projects/:team/feature_flags/:id/activity': () => [500, { detail: 'Server error' }] } })
        renderBanner(draftExperiment())

        expect(await screen.findByText(/can't launch until the flag is restored/)).toBeInTheDocument()
        expect(screen.queryByText(/deleted it/)).not.toBeInTheDocument()
        expect(restoreButtons().length).toBeGreaterThan(0)
    })

    it.each([
        {
            state: 'when the viewer cannot edit the flag',
            response: () => [200, { ...flagFromFlagApi, can_edit: false }],
        },
        {
            state: 'when the flag cannot be read',
            response: () => [403, { detail: 'You do not have access to this feature flag.' }],
        },
    ])('offers no restore $state', async ({ response }) => {
        useMocks({ get: { '/api/projects/:team/feature_flags/:id': response } })
        renderBanner(draftExperiment())

        expect(await screen.findByText(/Ask someone with edit access to restore it/)).toBeInTheDocument()
        expect(restoreButtons()).toHaveLength(0)
    })

    it('offers no restore for a flag on the new config format', async () => {
        const v2Flag = { ...deletedFlag, filters: { version: 2, rules: [] } }
        useMocks({ get: { '/api/projects/:team/feature_flags/:id': { ...flagFromFlagApi, ...v2Flag } } })
        renderBanner(draftExperiment(v2Flag))

        expect(await screen.findByText(/Restoring is not available for this flag yet/)).toBeInTheDocument()
        expect(restoreButtons()).toHaveLength(0)
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

        // The banner renders nothing while it reads the flag, so its logic shows that it never started.
        expect(deletedFlagBannerLogic.findMounted({ experimentId: EXPERIMENT_ID, flagId: FLAG_ID })).toBeNull()
        expect(screen.queryByText(/feature flag is deleted/)).not.toBeInTheDocument()
    })

    it('stays hidden when the flag is not deleted', () => {
        renderBanner(draftExperiment({ ...deletedFlag, deleted: false }))

        expect(deletedFlagBannerLogic.findMounted({ experimentId: EXPERIMENT_ID, flagId: FLAG_ID })).toBeNull()
        expect(screen.queryByText(/feature flag is deleted/)).not.toBeInTheDocument()
    })
})
