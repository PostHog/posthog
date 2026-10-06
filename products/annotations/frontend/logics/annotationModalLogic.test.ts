import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'
import { AnnotationScope, AnnotationType } from '~/types'

import { annotationModalHostLogic } from './annotationModalHostLogic'
import { annotationModalLogic } from './annotationModalLogic'

const annotation = (id: number, content: string): AnnotationType => ({
    id,
    scope: AnnotationScope.Project,
    content,
    date_marker: dayjs('2026-09-28T12:00:00.000Z'),
    created_at: dayjs('2026-09-28T12:00:00.000Z'),
    updated_at: '2026-09-28T12:00:00.000Z',
})

describe('annotationModalLogic', () => {
    let logic: ReturnType<typeof annotationModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        annotationModalHostLogic.mount()
        annotationModalHostLogic.actions.openModalToEditAnnotation(annotation(1, 'First annotation'))
        logic = annotationModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        annotationModalHostLogic.unmount()
    })

    it('updates the form when the open annotation changes', async () => {
        const nextAnnotation = annotation(2, 'Second annotation')

        await expectLogic(logic, () => {
            annotationModalHostLogic.actions.openModalToEditAnnotation(nextAnnotation)
        }).toFinishAllListeners()

        expect(logic.values.existingModalAnnotation).toMatchObject({ id: nextAnnotation.id })
        expect(logic.values.annotationModal.content).toBe(nextAnnotation.content)
    })
})
