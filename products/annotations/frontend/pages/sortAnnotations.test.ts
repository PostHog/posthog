import { dayjs } from 'lib/dayjs'

import { AnnotationScope, AnnotationType } from '~/types'

import { sortAnnotations } from './sortAnnotations'

const annotation = (id: number, date: string, scope: AnnotationScope, creator: string): AnnotationType =>
    ({
        id,
        content: `Annotation ${id}`,
        date_marker: dayjs(date),
        created_at: dayjs(date),
        scope,
        created_by: { first_name: creator },
    }) as AnnotationType

const ANNOTATIONS = [
    annotation(1, '2026-01-02', AnnotationScope.Project, 'Bea'),
    annotation(2, '2026-01-03', AnnotationScope.Insight, 'Cal'),
    annotation(3, '2026-01-01', AnnotationScope.Organization, 'Ada'),
]

describe('sortAnnotations', () => {
    test.each([
        { sort: { id: 'date_marker', desc: true }, ids: [2, 1, 3] },
        { sort: { id: 'date_marker', desc: false }, ids: [3, 1, 2] },
        { sort: { id: 'scope', desc: false }, ids: [2, 1, 3] },
        { sort: { id: 'created_by', desc: false }, ids: [3, 1, 2] },
        { sort: { id: 'annotation', desc: false }, ids: [1, 2, 3] },
    ])('orders rows by $sort.id, desc $sort.desc', ({ sort, ids }) => {
        expect(sortAnnotations(ANNOTATIONS, [sort]).map((row) => row.id)).toEqual(ids)
    })
})
