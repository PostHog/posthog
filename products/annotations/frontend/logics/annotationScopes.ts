import { AnnotationScope } from '~/types'

export const annotationScopeToName: Record<AnnotationScope, string> = {
    [AnnotationScope.Insight]: 'Insight',
    [AnnotationScope.Dashboard]: 'Dashboard',
    [AnnotationScope.Project]: 'Project',
    [AnnotationScope.Organization]: 'Organization',
}

export const annotationScopeToLevel: Record<AnnotationScope, number> = {
    [AnnotationScope.Insight]: 0,
    [AnnotationScope.Dashboard]: 1,
    [AnnotationScope.Project]: 2,
    [AnnotationScope.Organization]: 3,
}
