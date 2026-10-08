import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { editWorkflowsWidgetModalLogic } from './editWorkflowsWidgetModalLogic'

describe('editWorkflowsWidgetModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('keeps the tile bar filters when saving a new limit', async () => {
        const onSave = jest.fn().mockResolvedValue(undefined)
        const logic = editWorkflowsWidgetModalLogic({
            config: { limit: 10, status: 'draft', workflowType: 'broadcast', dateRange: { date_from: '-30d' } },
            onSave,
            onClose: jest.fn(),
            defaultTitle: 'Workflow activity',
        })
        logic.mount()

        logic.actions.setLimit(5)
        await expectLogic(logic, () => logic.actions.submit())
            .toFinishAllListeners()
            .toMatchValues({ saving: false })

        expect(onSave).toHaveBeenCalledWith(
            { limit: 5, status: 'draft', workflowType: 'broadcast', dateRange: { date_from: '-30d' } },
            {}
        )
        logic.unmount()
    })
})
