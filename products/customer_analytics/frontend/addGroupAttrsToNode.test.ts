import { NotebookNodeType } from 'scenes/notebooks/types'

import { GroupTypeIndex } from '~/types'

import { addGroupAttrsToNode } from './customerProfileLogic'

describe('addGroupAttrsToNode', () => {
    // The group properties node keys groupLogic on `${groupTypeIndex}-${groupKey}`. If these attrs go
    // missing the node mounts groupLogic unkeyed and the properties panel crashes on the group profile.
    it('passes groupKey and groupTypeIndex to the group properties node', () => {
        const result = addGroupAttrsToNode({
            attrs: { groupKey: 'acme', groupTypeIndex: 0 as GroupTypeIndex },
            node: { type: NotebookNodeType.GroupProperties },
        })

        expect(result.attrs).toMatchObject({ groupKey: 'acme', groupTypeIndex: 0 })
    })
})
