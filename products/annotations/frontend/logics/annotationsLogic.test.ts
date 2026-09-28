import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AnnotationScope, RawAnnotationType } from '~/types'

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
        getAnnotationSpy = jest.spyOn(api.annotations, 'get').mockResolvedValue(annotation)
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

        expect(getAnnotationSpy).toHaveBeenCalledWith(annotation.id)
        expect(annotationModalHostLogic.values.modalRequest).toMatchObject({ annotation: { id: annotation.id } })
    })
})
