import { AnnotationType } from '~/types'

import { annotationScopeToLevel } from '../logics/annotationModalLogic'

export interface AnnotationSort {
    id: string
    desc: boolean
}

const annotationCreatorName = (annotation: AnnotationType): string =>
    annotation.created_by?.first_name || annotation.created_by?.email || ''

/** The sort key of each sortable column, as the Lemon table's sorters compare them. */
export const ANNOTATION_SORT_KEYS: Record<string, (annotation: AnnotationType) => number | string> = {
    date_marker: (annotation) => annotation.date_marker?.valueOf() ?? 0,
    scope: (annotation) => annotationScopeToLevel[annotation.scope],
    created_by: annotationCreatorName,
    created_at: (annotation) => annotation.created_at?.valueOf() ?? 0,
}

/** The quill table only reports sort clicks when it is controlled, so the rows are sorted here. */
export function sortAnnotations(annotations: AnnotationType[], sorting: AnnotationSort[]): AnnotationType[] {
    const [sort] = sorting
    const key = sort ? ANNOTATION_SORT_KEYS[sort.id] : undefined
    if (!sort || !key) {
        return annotations
    }
    const direction = sort.desc ? -1 : 1
    return [...annotations].sort((a, b) => {
        const left = key(a)
        const right = key(b)
        const order =
            typeof left === 'string' && typeof right === 'string'
                ? left.localeCompare(right)
                : Number(left) - Number(right)
        return order * direction
    })
}
