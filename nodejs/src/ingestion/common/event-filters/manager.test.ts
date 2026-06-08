import { EventFilterManager } from './manager'

describe('EventFilterManager', () => {
    const mockPostgres = {
        query: jest.fn(),
    } as any

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('returns null for unknown team', async () => {
        mockPostgres.query.mockResolvedValue({ rows: [] })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))
        expect(manager.getFilter(999)).toBeNull()
    })

    it('returns filter for team in live mode', async () => {
        mockPostgres.query.mockResolvedValue({
            rows: [
                {
                    id: 'filter-1',
                    team_id: 1,
                    mode: 'live',
                    filter_tree: {
                        type: 'or',
                        children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: '$drop' }],
                    },
                },
            ],
        })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))

        const filter = manager.getFilter(1)
        expect(filter).not.toBeNull()
        expect(filter!.id).toBe('filter-1')
        expect(filter!.mode).toBe('live')
    })

    it('returns filter for team in dry_run mode', async () => {
        mockPostgres.query.mockResolvedValue({
            rows: [
                {
                    id: 'filter-dry',
                    team_id: 1,
                    mode: 'dry_run',
                    filter_tree: {
                        type: 'condition',
                        field: 'event_name',
                        operator: 'exact',
                        value: '$test',
                    },
                },
            ],
        })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))

        const filter = manager.getFilter(1)
        expect(filter).not.toBeNull()
        expect(filter!.mode).toBe('dry_run')
    })

    it('returns null for filter with no conditions (empty tree)', async () => {
        mockPostgres.query.mockResolvedValue({
            rows: [
                {
                    id: 'filter-empty',
                    team_id: 1,
                    mode: 'live',
                    filter_tree: { type: 'or', children: [] },
                },
            ],
        })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))

        expect(manager.getFilter(1)).toBeNull()
    })

    it('skips rows with invalid filter_tree', async () => {
        mockPostgres.query.mockResolvedValue({
            rows: [
                {
                    id: 'bad-filter',
                    team_id: 1,
                    mode: 'live',
                    filter_tree: { type: 'invalid' },
                },
                {
                    id: 'good-filter',
                    team_id: 2,
                    mode: 'live',
                    filter_tree: {
                        type: 'condition',
                        field: 'event_name',
                        operator: 'exact',
                        value: 'test',
                    },
                },
            ],
        })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))

        expect(manager.getFilter(1)).toBeNull()
        expect(manager.getFilter(2)).not.toBeNull()
        expect(manager.getFilter(2)!.id).toBe('good-filter')
    })

    it('skips rows with empty condition value', async () => {
        mockPostgres.query.mockResolvedValue({
            rows: [
                {
                    id: 'empty-value',
                    team_id: 1,
                    mode: 'live',
                    filter_tree: {
                        type: 'condition',
                        field: 'event_name',
                        operator: 'exact',
                        value: '',
                    },
                },
            ],
        })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))

        expect(manager.getFilter(1)).toBeNull()
    })

    it('handles multiple teams', async () => {
        mockPostgres.query.mockResolvedValue({
            rows: [
                {
                    id: 'f1',
                    team_id: 1,
                    mode: 'live',
                    filter_tree: { type: 'condition', field: 'event_name', operator: 'exact', value: 'a' },
                },
                {
                    id: 'f2',
                    team_id: 2,
                    mode: 'dry_run',
                    filter_tree: { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot' },
                },
            ],
        })
        const manager = new EventFilterManager(mockPostgres)
        await new Promise((r) => setTimeout(r, 100))

        expect(manager.getFilter(1)!.id).toBe('f1')
        expect(manager.getFilter(2)!.id).toBe('f2')
        expect(manager.getFilter(3)).toBeNull()
    })
})
