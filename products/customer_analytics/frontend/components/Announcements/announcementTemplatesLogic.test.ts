import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { announcementTemplatesLogic } from './announcementTemplatesLogic'

const TEMPLATE = {
    id: 't1',
    name: 'Onboarding nudge',
    message: 'Welcome aboard!',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    created_by: null,
}

describe('announcementTemplatesLogic', () => {
    let logic: ReturnType<typeof announcementTemplatesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/announcement_templates/': { results: [TEMPLATE], count: 1 },
            },
            post: {
                '/api/projects/:team_id/announcement_templates/': TEMPLATE,
            },
            put: {
                '/api/projects/:team_id/announcement_templates/:id/': TEMPLATE,
            },
            delete: {
                '/api/projects/:team_id/announcement_templates/:id/': {},
            },
        })
        initKeaTests(true, MOCK_DEFAULT_TEAM)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads templates on mount', async () => {
        logic = announcementTemplatesLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadTemplates', 'loadTemplatesSuccess'])
            .toMatchValues({ templates: [TEMPLATE] })
    })

    it('blocks save until both a name and a message are set', async () => {
        logic = announcementTemplatesLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ saveDisabledReason: 'Enter a name' })
        logic.actions.setFormName('Renewal')
        await expectLogic(logic).toMatchValues({ saveDisabledReason: 'Enter a message' })
        logic.actions.setFormMessage('Time to renew')
        await expectLogic(logic).toMatchValues({ saveDisabledReason: undefined })
    })

    it('seeds the editor body from the composer draft on "save as template"', async () => {
        logic = announcementTemplatesLogic()
        logic.mount()
        logic.actions.openCreateEditor('Drafted in the composer')
        await expectLogic(logic).toMatchValues({
            editorOpen: true,
            editingTemplateId: null,
            formMessage: 'Drafted in the composer',
            formName: '',
        })
    })

    it('creates a template, closes the editor, and reloads the list', async () => {
        logic = announcementTemplatesLogic()
        logic.mount()
        logic.actions.openCreateEditor('Welcome aboard!')
        logic.actions.setFormName('Onboarding nudge')
        await expectLogic(logic, () => {
            logic.actions.saveTemplate()
        })
            .toDispatchActions(['saveTemplate', 'loadTemplates'])
            .toFinishAllListeners()
        expect(logic.values.editorOpen).toBe(false)
        expect(logic.values.saving).toBe(false)
    })

    it('prefills the editor when editing an existing template', async () => {
        logic = announcementTemplatesLogic()
        logic.mount()
        logic.actions.openEditEditor(TEMPLATE)
        await expectLogic(logic).toMatchValues({
            editorOpen: true,
            editingTemplateId: 't1',
            formName: 'Onboarding nudge',
            formMessage: 'Welcome aboard!',
        })
    })

    it('deletes a template and reloads the list', async () => {
        logic = announcementTemplatesLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.deleteTemplate('t1')
        })
            .toDispatchActions(['deleteTemplate', 'loadTemplates'])
            .toFinishAllListeners()
    })
})
