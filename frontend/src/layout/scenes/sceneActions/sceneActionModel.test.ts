import { SceneAction, buildSceneActionMenu, pinnedSceneActions } from './sceneActionModel'

const noop = (): void => {}

function action(id: string, group: string, pinned?: SceneAction['pinned']): SceneAction {
    return { id, group, label: id, onSelect: noop, pinned }
}

describe('scene action model', () => {
    test('builds menus in canonical order with metadata on the top level', () => {
        const menu = buildSceneActionMenu(
            [
                action('help-docs', 'help'),
                action('tags', 'metadata'),
                action('debug', 'staff'),
                action('rename', 'edit'),
                action('custom-row', 'Insights'),
                action('export', 'file'),
            ],
            'insight'
        )
        expect(menu.map((item) => [item.id, item.dataAttr])).toEqual([
            ['group:file', 'insight-menubar-file'],
            ['group:edit', 'insight-menubar-edit'],
            ['group:Insights', 'insight-menubar-Insights'],
            ['tags', 'tags'],
            ['group:staff', 'insight-menubar-staff'],
            ['group:help', 'insight-menubar-help'],
        ])
    })

    test('puts the primary action last and drops pins over each variant cap', () => {
        const pinned = pinnedSceneActions([
            action('menu-only', 'file'),
            action('second-primary', 'file', { order: 5, variant: 'primary' }),
            action('third-secondary', 'edit', { order: 4, variant: 'secondary' }),
            action('first-secondary', 'edit', { order: 2, variant: 'secondary' }),
            action('primary', 'file', { order: 1, variant: 'primary' }),
            action('second-secondary', 'view', { order: 3, variant: 'secondary' }),
        ])
        expect(pinned.map((item) => item.id)).toEqual(['first-secondary', 'second-secondary', 'primary'])
    })
})
