import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { createDottedViewTree } from './queryDatabaseLogic'

describe('createDottedViewTree', () => {
    it('groups dotted views into folders and creates an index node when a folder is also a view', () => {
        const items: TreeDataItem[] = [
            {
                id: 'view-ab',
                name: 'a.b',
                type: 'node',
                record: { type: 'view' },
                children: [],
            },
            {
                id: 'view-abc',
                name: 'a.b.c',
                type: 'node',
                record: { type: 'view' },
                children: [],
            },
        ]

        const tree = createDottedViewTree(items)

        expect(tree).toHaveLength(1)
        expect(tree[0].name).toBe('a')
        expect(tree[0].record?.type).toBe('view-folder')

        const bFolder = tree[0].children?.[0]
        expect(bFolder?.name).toBe('b')
        expect(bFolder?.record?.type).toBe('view-folder')
        expect(bFolder?.children?.map((child) => child.name)).toEqual(['index', 'c'])
        expect(bFolder?.children?.[0].record?.type).toBe('view')
        expect(bFolder?.children?.[1].record?.type).toBe('view')
    })
})
