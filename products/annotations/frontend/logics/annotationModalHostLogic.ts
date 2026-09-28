import { MakeLogicType, actions, kea, path, reducers } from 'kea'

import type { Dayjs } from 'lib/dayjs'

import type { AnnotationType, DashboardBasicType, InsightModel } from '~/types'

export interface AnnotationModalHostValues {
    isModalOpen: boolean
    modalRequest: AnnotationModalRequest | null
}

export interface AnnotationModalRequest {
    annotation: AnnotationType | null
    dashboardId: DashboardBasicType['id'] | null
    initialDate: Dayjs | null
    insightId: InsightModel['id'] | null
}

export interface AnnotationModalHostActions {
    closeModal: () => { value: true }
    openModalToCreateAnnotation: (
        initialDate?: Dayjs | null,
        insightId?: InsightModel['id'] | null,
        dashboardId?: DashboardBasicType['id'] | null
    ) => AnnotationModalRequest
    openModalToEditAnnotation: (
        annotation: AnnotationType,
        insightId?: InsightModel['id'] | null,
        dashboardId?: DashboardBasicType['id'] | null
    ) => AnnotationModalRequest
}

export type annotationModalHostLogicType = MakeLogicType<AnnotationModalHostValues, AnnotationModalHostActions>

export const annotationModalHostLogic = kea<annotationModalHostLogicType>([
    path(['scenes', 'annotations', 'annotationModalHostLogic']),
    actions({
        openModalToCreateAnnotation: (
            initialDate?: Dayjs | null,
            insightId?: InsightModel['id'] | null,
            dashboardId?: DashboardBasicType['id'] | null
        ) => ({
            annotation: null,
            initialDate: initialDate ?? null,
            insightId: insightId ?? null,
            dashboardId: dashboardId ?? null,
        }),
        openModalToEditAnnotation: (
            annotation: AnnotationType,
            insightId?: InsightModel['id'] | null,
            dashboardId?: DashboardBasicType['id'] | null
        ) => ({ annotation, initialDate: null, insightId: insightId ?? null, dashboardId: dashboardId ?? null }),
        closeModal: true,
    }),
    reducers({
        isModalOpen: [
            false,
            {
                openModalToCreateAnnotation: () => true,
                openModalToEditAnnotation: () => true,
                closeModal: () => false,
            },
        ],
        modalRequest: [
            null as AnnotationModalRequest | null,
            {
                openModalToCreateAnnotation: (_, request) => request,
                openModalToEditAnnotation: (_, request) => request,
                closeModal: () => null,
            },
        ],
    }),
])
