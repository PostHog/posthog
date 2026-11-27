import { arrangeablePanes } from './todayRailLayout'
import type { TodayRailPane } from './todayShellLogic'

describe('arrangeablePanes', () => {
    const railPanes: TodayRailPane[] = ['home', 'spaces', 'analytics', 'people', 'release', 'monitor', 'products']

    test.each<[string, TodayRailPane[] | null, TodayRailPane[], TodayRailPane[]]>([
        [
            'no saved order keeps the default, without the locked and pinned panes',
            null,
            railPanes,
            ['spaces', 'analytics', 'people', 'release', 'monitor'],
        ],
        [
            'a saved order wins',
            ['people', 'analytics', 'spaces', 'release', 'monitor'],
            railPanes,
            ['people', 'analytics', 'spaces', 'release', 'monitor'],
        ],
        [
            'a pane a flag turns on later lands right after the pane it follows by default',
            ['people', 'analytics', 'spaces', 'monitor'],
            railPanes,
            ['people', 'release', 'analytics', 'spaces', 'monitor'],
        ],
        [
            'a pane whose flag turns off leaves the saved order',
            ['people', 'release', 'analytics', 'spaces', 'monitor'],
            railPanes.filter((pane) => pane !== 'release'),
            ['people', 'analytics', 'spaces', 'monitor'],
        ],
    ])('%s', (_, order, panes, expected) => {
        expect(arrangeablePanes(order, panes)).toEqual(expected)
    })
})
