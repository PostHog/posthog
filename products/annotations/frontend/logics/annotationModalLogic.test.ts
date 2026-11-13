import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { AnnotationScope, AnnotationType, SidePanelTab } from '~/types'

import * as generatedApi from '../generated/api'
import type { AnnotationApi } from '../generated/api.schemas'
import { annotationModalLogic } from './annotationModalLogic'

describe('annotationModalLogic', () => {
    let updateSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        updateSpy = jest.spyOn(generatedApi, 'annotationsPartialUpdate').mockResolvedValue({ id: 1 } as AnnotationApi)
    })

    afterEach(() => {
        updateSpy.mockRestore()
    })

    it('keeps the draft when its chart unmounts and another panel opens', () => {
        const unmountPanel = sidePanelStateLogic.mount()
        const logic = annotationModalLogic()
        const unmount = logic.mount()
        logic.actions.openModalToCreateAnnotation(null, 7)
        logic.actions.setAnnotationModalValue('content', 'Deployment notes')
        unmount()

        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Annotations)
        const unmountEditor = logic.mount()
        expect(logic.values.annotationModal).toMatchObject({ content: 'Deployment notes', dashboardItemId: 7 })
        expect(logic.values.isModalOpen).toBe(true)

        logic.actions.closeModal()
        expect(logic.values.annotationModal.content).toBe('')
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        unmountEditor()
        unmountPanel()
    })

    it('discards the draft when the current project changes', () => {
        const logic = annotationModalLogic()
        logic.mount()
        logic.actions.openModalToCreateAnnotation()
        logic.actions.setAnnotationModalValue('content', 'Project-specific note')

        teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, id: 99 })

        expect(logic.values.isModalOpen).toBe(false)
        expect(logic.values.annotationModal.content).toBe('')
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    it.each([
        {
            name: 'omits the stored insight when edited off an insight',
            stored: { scope: AnnotationScope.Organization, dashboard_item: 99 },
            insightId: null,
            dashboardId: null,
            newScope: null,
            expected: { scope: AnnotationScope.Organization, dashboard_id: null },
            absent: ['dashboard_item'],
        },
        {
            name: 'moves the annotation to the insight it is edited from',
            stored: { scope: AnnotationScope.Project, dashboard_item: 99 },
            insightId: 7,
            dashboardId: null,
            newScope: AnnotationScope.Insight,
            expected: { scope: AnnotationScope.Insight, dashboard_item: 7 },
            absent: [],
        },
        {
            name: 'takes the open dashboard when a row without one moves to dashboard scope',
            stored: { scope: AnnotationScope.Project, dashboard_id: null },
            insightId: 7,
            dashboardId: 5,
            newScope: AnnotationScope.Dashboard,
            expected: { scope: AnnotationScope.Dashboard, dashboard_id: 5 },
            absent: [],
        },
        {
            name: 'keeps a project row off the dashboard it is edited from',
            stored: { scope: AnnotationScope.Project, dashboard_id: null },
            insightId: 7,
            dashboardId: 5,
            newScope: null,
            expected: { scope: AnnotationScope.Project, dashboard_id: null },
            absent: [],
        },
    ])('$name', async ({ stored, insightId, dashboardId, newScope, expected, absent }) => {
        const annotation: AnnotationType = {
            id: 1,
            content: 'Release',
            date_marker: dayjs('2024-01-01T00:00:00Z'),
            created_at: dayjs('2024-01-01T00:00:00Z'),
            updated_at: '2024-01-01T00:00:00Z',
            dashboard_item: null,
            dashboard_id: null,
            ...stored,
        }
        const logic = annotationModalLogic()
        logic.mount()

        logic.actions.openModalToCreateAnnotation(null, 42, 8)
        logic.actions.openModalToEditAnnotation(annotation, insightId, dashboardId)
        if (newScope) {
            logic.actions.setAnnotationModalValue('scope', newScope)
        }
        logic.actions.submitAnnotationModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(updateSpy).toHaveBeenCalledTimes(1)
        const body = updateSpy.mock.calls[0][2]
        expect(body).toMatchObject(expected)
        for (const key of absent) {
            expect(body).not.toHaveProperty(key)
        }
    })
})
