import { useActions, useValues } from 'kea'
import { annotationsLogic } from 'lib/components/Annotations'

const noop = (): void => {}

export const getAnnotationActionsAndValues = (isSharedMode: boolean, dashboardItemId: string): Record<string, any> => {
    if (isSharedMode) {
        return {
            createAnnotation: noop,
            createAnnotationNow: noop,
            updateDiffType: noop,
            createGlobalAnnotation: noop,
            annotationsList: [],
            annotationsLoading: false,
        }
    }
    const {
        createAnnotation,
        createAnnotationNow,
        updateDiffType,
        createGlobalAnnotation,
        // eslint-disable-next-line react-hooks/rules-of-hooks
    } = useActions(annotationsLogic({ pageKey: dashboardItemId || null }))
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { annotationsList, annotationsLoading } = useValues(annotationsLogic({ pageKey: dashboardItemId || null }))
    return {
        createAnnotation,
        createAnnotationNow,
        updateDiffType,
        createGlobalAnnotation,
        annotationsList,
        annotationsLoading,
    }
}
