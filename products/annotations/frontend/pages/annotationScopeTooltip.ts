import { AnnotationScope, AnnotationType } from '~/types'

/** What an annotation's scope covers, named for the insight, dashboard, project or organization it applies to. */
export function annotationScopeTooltip(
    annotation: AnnotationType,
    teamName: string | undefined,
    organizationName: string | undefined
): string {
    if (annotation.scope === AnnotationScope.Insight) {
        return `This annotation only applies to the "${annotation.insight_name}" insight`
    }
    if (annotation.scope === AnnotationScope.Dashboard) {
        return `This annotation applies to all insights on the ${annotation.dashboard_name} dashboard`
    }
    if (annotation.scope === AnnotationScope.Project) {
        return `This annotation applies to all insights in the ${teamName} project`
    }
    return `This annotation applies to all insights in the ${organizationName} organization`
}
