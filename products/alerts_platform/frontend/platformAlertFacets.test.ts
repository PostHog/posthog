import { platformAlertFacets } from './platformAlertFacets'

describe('platformAlertFacets', () => {
    it('gives each label key its own facet, whose values filter as key:value', () => {
        const facets = platformAlertFacets({
            states: [{ value: 'not_firing', count: 2 }],
            mutes: [],
            source_kinds: [{ value: 'logs', count: 2 }],
            labels: [{ key: 'team', values: [{ value: 'apm', count: 2 }] }],
        })

        expect(facets.map(({ key, title, param, options }) => ({ key, title, param, options }))).toEqual([
            { key: 'state', title: 'State', param: 'state', options: [{ value: 'not_firing', label: 'OK', count: 2 }] },
            { key: 'muted', title: 'Muted', param: 'muted', options: [] },
            {
                key: 'source_kind',
                title: 'Type',
                param: 'source_kind',
                options: [{ value: 'logs', label: 'Logs', count: 2 }],
            },
            {
                key: 'label:team',
                title: 'team',
                param: 'label',
                options: [{ value: 'team:apm', label: 'apm', count: 2 }],
            },
        ])
    })
})
