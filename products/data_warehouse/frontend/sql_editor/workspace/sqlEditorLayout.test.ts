import {
    DEFAULT_SQL_EDITOR_LAYOUT,
    SqlEditorLayout,
    moveInspectorTab,
    normalizeSqlEditorLayout,
    openInspectorTab,
    setInspectorTabVisible,
} from './sqlEditorLayout'

const layoutWith = (inspector: Partial<SqlEditorLayout['inspector']>): SqlEditorLayout => ({
    ...DEFAULT_SQL_EDITOR_LAYOUT,
    inspector: { ...DEFAULT_SQL_EDITOR_LAYOUT.inspector, ...inspector },
})

describe('sqlEditorLayout', () => {
    test.each([
        ['nothing stored', undefined, DEFAULT_SQL_EDITOR_LAYOUT],
        ['a string', 'right', DEFAULT_SQL_EDITOR_LAYOUT],
        [
            'unknown and duplicate tabs',
            { inspector: { tabs: ['history', 'lineage', 'history', 'schema'], activeTab: 'lineage' } },
            layoutWith({ tabs: ['history', 'schema'], activeTab: 'history' }),
        ],
        [
            'an empty tab list',
            { inspector: { tabs: [], open: false, side: 'left' } },
            layoutWith({ open: false, side: 'left' }),
        ],
        [
            'an unknown side and placement',
            { inspector: { side: 'top' }, results: { placement: 'floating' } },
            DEFAULT_SQL_EDITOR_LAYOUT,
        ],
    ])('reads %s back as a usable layout', (_, stored, expected) => {
        expect(normalizeSqlEditorLayout(stored)).toEqual(expected)
    })

    it('keeps the last tab when asked to hide it', () => {
        const onlySchema = layoutWith({ tabs: ['schema'] })
        expect(setInspectorTabVisible(onlySchema, 'schema', false)).toBe(onlySchema)
    })

    it('moves the active tab off a tab that gets hidden', () => {
        const layout = setInspectorTabVisible(layoutWith({ activeTab: 'variables' }), 'variables', false)
        expect(layout.inspector).toMatchObject({ tabs: ['schema', 'history'], activeTab: 'schema' })
    })

    it('shows a hidden tab in its usual place when it is opened', () => {
        const layout = openInspectorTab(layoutWith({ tabs: ['schema', 'history'], open: false }), 'variables')
        expect(layout.inspector).toMatchObject({
            open: true,
            tabs: ['schema', 'variables', 'history'],
            activeTab: 'variables',
        })
    })

    it('moves a tab within the bounds of the list', () => {
        expect(moveInspectorTab(DEFAULT_SQL_EDITOR_LAYOUT, 'history', -4).inspector.tabs).toEqual([
            'history',
            'schema',
            'variables',
        ])
    })
})
