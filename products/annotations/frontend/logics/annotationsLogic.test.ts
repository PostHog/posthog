import { expectLogic } from 'kea-test-utils'

import { annotationsModel } from '~/models/annotationsModel'
import { initKeaTests } from '~/test/init'
import { AnnotationScope, RawAnnotationType } from '~/types'

import * as annotationsApi from '../generated/api'
import type { AnnotationApi } from '../generated/api.schemas'
import { annotationModalHostLogic } from './annotationModalHostLogic'
import { annotationsLogic } from './annotationsLogic'

const annotation: RawAnnotationType = {
    id: 42,
    scope: AnnotationScope.Project,
    content: 'Release deployed',
    date_marker: '2026-09-28T12:00:00.000Z',
    created_at: '2026-09-28T12:00:00.000Z',
    updated_at: '2026-09-28T12:00:00.000Z',
}

describe('annotationsLogic', () => {
    let logic: ReturnType<typeof annotationsLogic.build>
    let getAnnotationSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getAnnotationSpy = jest
            .spyOn(annotationsApi, 'annotationsRetrieve')
            .mockResolvedValue(annotation as unknown as AnnotationApi)
        annotationModalHostLogic.mount()
        logic = annotationsLogic()
        logic.mount()
    })

    afterEach(() => {
        getAnnotationSpy.mockRestore()
        logic.unmount()
        annotationModalHostLogic.unmount()
    })

    it('loads an annotation that is not in the initial list', async () => {
        await expectLogic(logic, () => {
            logic.actions.openAnnotationFromUrl(annotation.id)
        }).toFinishAllListeners()

        expect(getAnnotationSpy).toHaveBeenCalledWith(expect.any(String), annotation.id)
        expect(annotationModalHostLogic.values.modalRequest).toMatchObject({ annotation: { id: annotation.id } })
    })

    it('opens an annotation already loaded in the list', async () => {
        annotationsModel.actions.appendAnnotations([annotation])

        await expectLogic(logic, () => {
            logic.actions.openAnnotationFromUrl(annotation.id)
        }).toFinishAllListeners()

        expect(getAnnotationSpy).not.toHaveBeenCalled()
        expect(annotationModalHostLogic.values.modalRequest).toMatchObject({ annotation: { id: annotation.id } })
    })

    it('adds a visible annotation fetched from a URL after an update', async () => {
        await expectLogic(logic, () => {
            logic.actions.openAnnotationFromUrl(annotation.id)
        }).toFinishAllListeners()

        annotationsModel.actions.replaceAnnotation({ ...annotation, content: 'Updated release deployed' })

        expect(annotationsModel.values.rawAnnotations).toMatchObject([
            { id: annotation.id, content: 'Updated release deployed' },
        ])
    })

    it('does not add a hidden annotation fetched from a URL after an update', async () => {
        annotationsModel.actions.replaceAnnotation({ ...annotation, hidden_in_user_interface: true })

        expect(annotationsModel.values.rawAnnotations).toEqual([])
    })
})
