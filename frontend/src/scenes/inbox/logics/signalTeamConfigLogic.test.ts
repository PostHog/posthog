/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalTeamConfig } from '../types'
import { signalTeamConfigLogic } from './signalTeamConfigLogic'

describe('signalTeamConfigLogic', () => {
    let logic: ReturnType<typeof signalTeamConfigLogic.build>
    let serverConfig: SignalTeamConfig
    let lastPostBody: Partial<SignalTeamConfig> | null

    const mountWith = async (baseBranches: Record<string, string>): Promise<void> => {
        serverConfig = {
            id: 'cfg-1',
            autostart_enabled: true,
            default_autostart_priority: 'P4',
            autostart_base_branches: baseBranches,
        }
        lastPostBody = null
        useMocks({
            get: { '/api/projects/:team_id/signals/config/': () => [200, serverConfig] },
            post: {
                '/api/projects/:team_id/signals/config/': async ({ request }) => {
                    lastPostBody = (await request.json()) as Partial<SignalTeamConfig>
                    serverConfig = { ...serverConfig, ...lastPostBody }
                    return [200, serverConfig]
                },
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    afterEach(() => logic?.unmount())

    it('adds an override without clobbering existing repos, and clears the draft', async () => {
        await mountWith({ 'acme/web': 'staging' })
        logic.actions.setDraftBaseBranchRepo('Acme/API')
        logic.actions.setDraftBaseBranchBranch('  develop  ')
        logic.actions.addBaseBranchOverride()
        await expectLogic(logic).toFinishAllListeners()

        // The whole map is persisted: the existing repo survives, the new key is lowercased and the branch trimmed.
        expect(lastPostBody?.autostart_base_branches).toEqual({ 'acme/web': 'staging', 'acme/api': 'develop' })
        expect(logic.values.draftBaseBranchRepo).toBe('')
        expect(logic.values.draftBaseBranchBranch).toBe('')
        expect(logic.values.baseBranchOverrides).toEqual([
            { repo: 'acme/api', branch: 'develop' },
            { repo: 'acme/web', branch: 'staging' },
        ])
    })

    it.each([
        ['repo without a slash', 'acmeweb', 'develop'],
        ['blank branch', 'acme/api', '   '],
    ])('rejects an invalid override (%s) without calling the API', async (_label, repo, branch) => {
        await mountWith({ 'acme/web': 'staging' })
        logic.actions.setDraftBaseBranchRepo(repo)
        logic.actions.setDraftBaseBranchBranch(branch)
        logic.actions.addBaseBranchOverride()
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody).toBeNull()
        // Draft is preserved so the user can fix the input rather than retype it.
        expect(logic.values.draftBaseBranchRepo).toBe(repo)
        expect(logic.values.baseBranchOverrides).toEqual([{ repo: 'acme/web', branch: 'staging' }])
    })

    it('removes only the targeted override', async () => {
        await mountWith({ 'acme/web': 'staging', 'acme/api': 'develop' })
        logic.actions.removeBaseBranchOverride('acme/web')
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody?.autostart_base_branches).toEqual({ 'acme/api': 'develop' })
        expect(logic.values.baseBranchOverrides).toEqual([{ repo: 'acme/api', branch: 'develop' }])
    })
})
