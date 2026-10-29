import { LemonDialog } from '@posthog/lemon-ui'

import { FeatureFlagConfig, FeatureFlagType } from '~/types'

import { getFeatureFlagDeleteBlockers, openFeatureFlagDeleteDialog } from './featureFlagDeleteDialog'

const base: Partial<FeatureFlagType> = {
    key: 'my-flag',
    features: [],
    experiment_set_metadata: [],
    surveys: [],
    is_used_in_replay_settings: false,
}

describe('getFeatureFlagDeleteBlockers', () => {
    it('returns empty array when nothing blocks deletion', () => {
        expect(getFeatureFlagDeleteBlockers(base)).toEqual([])
    })

    it('blocks on an early access feature', () => {
        const flag = { ...base, features: [{ id: '1', name: 'My Feature' }] } as Partial<FeatureFlagType>
        const blockers = getFeatureFlagDeleteBlockers(flag)
        expect(blockers).toHaveLength(1)
        expect(blockers[0].kind).toBe('Early access feature')
        expect(blockers[0].name).toBe('My Feature')
    })

    it('blocks on a running experiment', () => {
        const flag = {
            ...base,
            experiment_set_metadata: [{ id: 1, name: 'My Experiment', is_running: true }],
        } as Partial<FeatureFlagType>
        const blockers = getFeatureFlagDeleteBlockers(flag)
        expect(blockers).toHaveLength(1)
        expect(blockers[0].kind).toBe('Running experiment')
        expect(blockers[0].name).toBe('My Experiment')
    })

    it('does not block on a stopped experiment', () => {
        const flag = {
            ...base,
            experiment_set_metadata: [{ id: 1, name: 'My Experiment', is_running: false }],
        } as Partial<FeatureFlagType>
        expect(getFeatureFlagDeleteBlockers(flag)).toEqual([])
    })

    it('blocks on a survey', () => {
        const flag = { ...base, surveys: [{ id: '1', name: 'My Survey' }] } as Partial<FeatureFlagType>
        const blockers = getFeatureFlagDeleteBlockers(flag)
        expect(blockers).toHaveLength(1)
        expect(blockers[0].kind).toBe('Survey')
        expect(blockers[0].name).toBe('My Survey')
    })

    it('blocks when used in replay settings', () => {
        const flag = { ...base, is_used_in_replay_settings: true } as Partial<FeatureFlagType>
        const blockers = getFeatureFlagDeleteBlockers(flag)
        expect(blockers).toHaveLength(1)
        expect(blockers[0].kind).toBe('Session replay')
    })

    it('accumulates multiple blockers', () => {
        const flag = {
            ...base,
            features: [{ id: '1', name: 'Feature A' }],
            experiment_set_metadata: [{ id: 1, name: 'Exp A', is_running: true }],
            surveys: [{ id: '1', name: 'Survey A' }],
            is_used_in_replay_settings: true,
        } as Partial<FeatureFlagType>
        expect(getFeatureFlagDeleteBlockers(flag).map((b) => b.kind)).toEqual([
            'Early access feature',
            'Running experiment',
            'Survey',
            'Session replay',
        ])
    })
})

describe('openFeatureFlagDeleteDialog', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['a v1 flag', { groups: [] }, 'Are you sure you want to delete "my-flag"?'],
        [
            'a rules v2 flag',
            { version: 2 },
            'Are you sure you want to delete "my-flag"? Deleting turns the flag off, and it can\'t be restored yet.',
        ],
    ])('warns that the delete is final for a flag that cannot be restored: %s', (_, filters, description) => {
        const open = jest.spyOn(LemonDialog, 'open').mockImplementation(() => undefined)

        openFeatureFlagDeleteDialog({ ...base, filters: filters as FeatureFlagConfig }, jest.fn())

        expect(open).toHaveBeenCalledWith(expect.objectContaining({ description }))
    })
})
