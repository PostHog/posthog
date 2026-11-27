import { urls } from 'scenes/urls'

import { AnnotationScope, AnnotationType } from '~/types'

import { annotationScopeToName } from '../logics/annotationModalLogic'

export interface AnnotationScopeOption {
    value: AnnotationType['scope']
    label: string
    tooltip?: JSX.Element | string | null
    disabledReason?: string | false
    /** Where the annotation's current insight or dashboard lives, when that differs from where it is being edited. */
    link?: string
}

/** The scopes an annotation can take in the modal, each with why it is unavailable here. */
export function annotationScopeOptions(
    existingModalAnnotation: AnnotationType | null,
    dashboardId: number | null | undefined,
    onSavedInsight: boolean
): AnnotationScopeOption[] {
    return [
        {
            value: AnnotationScope.Insight,
            label: annotationScopeToName[AnnotationScope.Insight],
            tooltip: existingModalAnnotation?.insight_name ? (
                existingModalAnnotation.insight_name
            ) : existingModalAnnotation?.insight_derived_name ? (
                <i>{existingModalAnnotation.insight_derived_name}</i>
            ) : undefined,
            disabledReason:
                (!onSavedInsight && 'You need to save the insight first.') ||
                // if existing annotation data in db (for backwards compatibility) doesn't have insight id set on it
                // we can't let them change scope to insight as we don't know which insight to map to
                (existingModalAnnotation
                    ? !existingModalAnnotation?.dashboard_item &&
                      'To select this scope, open this annotation on the target insight'
                    : undefined),
            link: existingModalAnnotation?.insight_short_id
                ? urls.insightView(existingModalAnnotation.insight_short_id)
                : undefined,
        },
        {
            value: AnnotationScope.Dashboard,
            label: annotationScopeToName[AnnotationScope.Dashboard],
            tooltip: existingModalAnnotation?.dashboard_name,
            disabledReason:
                (!dashboardId && 'To select this scope, open this annotation on the target dashboard') ||
                (existingModalAnnotation?.scope === AnnotationScope.Dashboard && 'Already scoped to dashboard') ||
                (existingModalAnnotation && existingModalAnnotation?.dashboard_name
                    ? dashboardId != existingModalAnnotation.dashboard_id &&
                      `To select this scope, open this annotation on the ${existingModalAnnotation?.dashboard_name} dashboard`
                    : undefined),
            link:
                existingModalAnnotation?.dashboard_id &&
                existingModalAnnotation?.scope !== AnnotationScope.Dashboard &&
                existingModalAnnotation.dashboard_id !== dashboardId
                    ? urls.dashboard(existingModalAnnotation.dashboard_id)
                    : undefined,
        },
        {
            value: AnnotationScope.Project,
            label: annotationScopeToName[AnnotationScope.Project],
        },
        {
            value: AnnotationScope.Organization,
            label: annotationScopeToName[AnnotationScope.Organization],
        },
    ]
}
