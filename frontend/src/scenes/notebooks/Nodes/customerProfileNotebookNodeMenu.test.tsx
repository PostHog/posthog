import { initKeaTests } from '~/test/init'

import { NotebookNodeType } from '../types'
import { getCustomerProfileRemoveMenuItem } from './customerProfileNotebookNodeMenu'

describe('customerProfileNotebookNodeMenu', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('does not create a remove menu item outside a customer profile canvas', () => {
        expect(getCustomerProfileRemoveMenuItem(NotebookNodeType.LLMTrace)).toBeNull()
    })
})
