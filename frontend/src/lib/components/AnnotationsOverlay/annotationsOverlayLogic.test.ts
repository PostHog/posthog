import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { insightLogic } from 'scenes/insights/insightLogic'

import { useMocks } from '~/mocks/jest'
import { annotationsModel, deserializeAnnotation } from '~/models/annotationsModel'
import { initKeaTests } from '~/test/init'
import { AnnotationScope, AnnotationType, InsightShortId, IntervalType, RawAnnotationType } from '~/types'

import { annotationsOverlayLogic } from './annotationsOverlayLogic'

jest.spyOn(Storage.prototype, 'getItem')

const MOCK_INSIGHT_SHORT_ID = 'abcdef' as InsightShortId
const MOCK_INSIGHT_NUMERIC_ID = 1
const MOCK_INSIGHT_NUMERIC_ID_2 = 2
const MOCK_DASHBOARD_ID = 1
const MOCK_DASHBOARD_ID_2 = 2
const MOCK_DASHBOARD_ID_3 = 2

const BASE_MOCK_ANNOTATION: Pick<
    RawAnnotationType,
    'creation_type' | 'created_at' | 'created_by' | 'updated_at' | 'deleted'
> = {
    creation_type: 'USR',
    created_by: {
        id: 5,
        uuid: '0182cb27-8dfc-0000-1f45-c16dc0de95ea',
        distinct_id: 'XoBG3ygtKV8635pAFkEWHKboT6me1MTVaJETde7dm8V',
        first_name: 'Employee 427',
        email: 'test@posthog.com',
    },
    created_at: '2022-08-26T12:22:00.892304Z',
    updated_at: '2022-08-29T11:21:25.022540Z',
    deleted: false,
}

/** ID 20 at 2022-08-10T04:00:00.000Z */
const MOCK_ANNOTATION_ORG_SCOPED: RawAnnotationType = {
    id: 20,
    content: 'MOCK_ANNOTATION_ORG_SCOPED',
    date_marker: '2022-08-10T04:00:00.000Z',
    dashboard_item: null,
    insight_short_id: null,
    insight_name: null,
    insight_derived_name: null,
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 10 at 2022-08-10T04:00:01.000Z */
const MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3: RawAnnotationType = {
    id: 10,
    content: 'MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3',
    date_marker: '2022-08-10T04:00:01.000Z', // A second after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    insight_derived_name: null,
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 17 at 2022-08-10T04:01:00.000Z */
const MOCK_ANNOTATION_PROJECT_SCOPED: RawAnnotationType = {
    id: 17,
    content: 'MOCK_ANNOTATION_PROJECT_SCOPED',
    date_marker: '2022-08-10T04:01:00.000Z', // A minute after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: null,
    insight_short_id: null,
    insight_name: null,
    insight_derived_name: null,
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 19 at 2022-08-10T05:00:00.000Z */
const MOCK_ANNOTATION_INSIGHT_1_SCOPED: RawAnnotationType = {
    id: 19,
    content: 'MOCK_ANNOTATION_INSIGHT_1_SCOPED',
    date_marker: '2022-08-10T05:00:00.000Z', // An hour after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 1,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    insight_derived_name: 'Pageview count',
    scope: AnnotationScope.Insight,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 20 at 2022-08-11T04:00:00.000Z */
const MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1: RawAnnotationType = {
    id: 20,
    content: 'MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1',
    date_marker: '2022-08-11T04:00:00.000Z', // A day after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    insight_derived_name: 'Pageview count',
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 21 at 2022-08-17T04:00:00.000Z */
const MOCK_ANNOTATION_INSIGHT_3_SCOPED: RawAnnotationType = {
    id: 21,
    content: 'MOCK_ANNOTATION_INSIGHT_3_SCOPED',
    date_marker: '2022-08-17T04:00:00.000Z', // A week after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    insight_derived_name: null,
    scope: AnnotationScope.Insight,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 40 at 2022-08-17T04:00:00.000Z */
const MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1: RawAnnotationType = {
    id: 40,
    content: 'MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1',
    date_marker: '2022-08-17T04:00:00.000Z', // A week after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: null,
    insight_derived_name: 'Pageview count',
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 22 at 2022-09-10T04:00:00.000Z */
const MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3: RawAnnotationType = {
    id: 22,
    content: 'MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3',
    date_marker: '2022-09-10T04:00:00.000Z', // A month after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    insight_derived_name: null,
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 23 at 2022-08-10T04:00:00.000Z */
const MOCK_ANNOTATION_DASHBOARD_SCOPED: RawAnnotationType = {
    id: 23,
    content: 'MOCK_ANNOTATION_DASHBOARD_SCOPED',
    date_marker: '2022-08-10T04:00:00.000Z',
    dashboard_id: MOCK_DASHBOARD_ID,
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: null,
    insight_name: null,
    insight_derived_name: null,
    scope: AnnotationScope.Dashboard,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 24 at 2022-08-10T04:00:00.000Z */
const MOCK_ANNOTATION_DASHBOARD_SCOPED_2: RawAnnotationType = {
    id: 24,
    content: 'MOCK_ANNOTATION_DASHBOARD_SCOPED_2',
    date_marker: '2022-08-10T04:00:00.000Z',
    dashboard_id: MOCK_DASHBOARD_ID_2,
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID_2,
    insight_short_id: null,
    insight_name: null,
    insight_derived_name: null,
    scope: AnnotationScope.Dashboard,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 25 at 2022-08-10T04:00:00.000Z */
const MOCK_ANNOTATION_DASHBOARD_SCOPED_3: RawAnnotationType = {
    id: 25,
    content: 'MOCK_ANNOTATION_DASHBOARD_SCOPED_3',
    date_marker: '2022-08-10T04:00:00.000Z',
    dashboard_id: MOCK_DASHBOARD_ID_3,
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID_2,
    insight_short_id: null,
    insight_name: null,
    insight_derived_name: null,
    scope: AnnotationScope.Dashboard,
    ...BASE_MOCK_ANNOTATION,
}

function useInsightMocks(interval: string = 'day', timezone: string = 'UTC'): void {
    const insight = {
        result: {},
        id: MOCK_INSIGHT_NUMERIC_ID,
        short_id: MOCK_INSIGHT_SHORT_ID,
        filters: { insight: 'TRENDS', interval },
        timezone,
    }
    useMocks({
        get: {
            '/api/environments/:team_id/insights/': () => {
                return [
                    200,
                    {
                        results: [insight],
                    },
                ]
            },
            [`/api/environments/:team_id/insights/${MOCK_INSIGHT_NUMERIC_ID}`]: () => {
                return [200, insight]
            },
            '/api/users/@me/': [200, {}],
        },
    })
}

function useAnnotationsMocks(): void {
    useMocks({
        get: {
            '/api/projects/:team_id/annotations/': {
                results: [
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_INSIGHT_3_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    MOCK_ANNOTATION_DASHBOARD_SCOPED_2,
                    MOCK_ANNOTATION_DASHBOARD_SCOPED_3,
                ],
            },
            '/api/users/@me/': [200, {}],
        },
    })
}

describe('annotationsOverlayLogic', () => {
    let logic: ReturnType<typeof annotationsOverlayLogic.build>

    beforeEach(() => {
        useAnnotationsMocks()
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads annotations on mount', async () => {
        useInsightMocks()

        logic = annotationsOverlayLogic({
            dashboardItemId: MOCK_INSIGHT_SHORT_ID,
            insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
            dates: [],
            ticks: [],
            dashboardId: MOCK_DASHBOARD_ID,
        })
        logic.mount()
        await expectLogic(annotationsModel).toDispatchActions(['loadAnnotations'])
    })

    describe('relevantAnnotations', () => {
        it('returns annotations scoped to the insight for a saved insight', async () => {
            useInsightMocks()

            logic = annotationsOverlayLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                dates: ['2022-01-01', '2023-01-01'],
                ticks: [{ value: 0 }, { value: 1 }],
                dashboardId: MOCK_DASHBOARD_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(
                insightLogic({
                    dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                    dashboardId: MOCK_DASHBOARD_ID,
                })
            ).toDispatchActions(['loadInsightSuccess'])
            await expectLogic(logic).toMatchValues({
                relevantAnnotations: [
                    // The annotation scoped to insight 3 should be omitted
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_DASHBOARD_SCOPED,
                ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
            })
        })

        it('returns annotations scoped to the dashboard or matching insight', async () => {
            useInsightMocks()

            logic = annotationsOverlayLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                dates: ['2022-01-01', '2023-01-01'],
                ticks: [{ value: 0 }, { value: 1 }],
                dashboardId: MOCK_DASHBOARD_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(
                insightLogic({
                    dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                    dashboardId: MOCK_DASHBOARD_ID,
                })
            ).toDispatchActions(['loadInsightSuccess'])
            await expectLogic(logic).toMatchValues({
                relevantAnnotations: [
                    // The annotation scoped to insight 3 should be omitted
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_DASHBOARD_SCOPED,
                ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
            })
        })

        it("returns only annotations scoped to the dashboard when insight id doesn't match", async () => {
            useInsightMocks()

            logic = annotationsOverlayLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID_2,
                dates: ['2022-01-01', '2023-01-01'],
                ticks: [{ value: 0 }, { value: 1 }],
                dashboardId: MOCK_DASHBOARD_ID_2,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(
                insightLogic({
                    dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                    dashboardId: MOCK_DASHBOARD_ID_2,
                })
            ).toDispatchActions(['loadInsightSuccess'])
            await expectLogic(logic).toMatchValues({
                relevantAnnotations: [
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                    // dashboard id matches
                    MOCK_ANNOTATION_DASHBOARD_SCOPED_2,
                    // insightNumericId == dashboard_item for 3
                    MOCK_ANNOTATION_DASHBOARD_SCOPED_3,
                ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
            })
        })

        it('returns annotations scoped to the project for a new insight', async () => {
            useInsightMocks()

            logic = annotationsOverlayLogic({
                dashboardItemId: 'new',
                insightNumericId: 'new',
                dashboardId: 0,
                dates: ['2022-01-01', '2023-01-01'],
                ticks: [{ value: 0 }, { value: 1 }],
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(logic).toMatchValues({
                relevantAnnotations: [
                    // The annotation scoped to insight 3 should be omitted
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
            })
        })

        it('excludes annotations that are outside of insight date range', async () => {
            useInsightMocks()

            logic = annotationsOverlayLogic({
                dashboardItemId: 'new',
                insightNumericId: 'new',
                dates: ['2022-09-01', '2022-10-01'],
                ticks: [{ value: 0 }, { value: 1 }],
                dashboardId: MOCK_DASHBOARD_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(logic).toMatchValues({
                relevantAnnotations: [
                    // This is the only September annotation
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
            })
        })
    })

    describe('groupedAnnotations', () => {
        const EXPECTED_GROUPINGS_BY_INTERVAL_AND_TIMEZONE: Record<
            string,
            Record<IntervalType, Record<string, AnnotationType[]>> // All IntervalType variants should be covered
        > = {
            UTC: {
                second: {
                    '2022-08-10 04:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED, MOCK_ANNOTATION_DASHBOARD_SCOPED].map(
                        (annotation) => deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-10 04:00:01+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-10 04:01:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-10 05:00:00+0000': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-11 04:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-17 04:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-09-10 04:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                },
                minute: {
                    '2022-08-10 04:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
                    '2022-08-10 04:01:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-10 05:00:00+0000': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-11 04:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-17 04:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-09-10 04:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                },
                hour: {
                    '2022-08-10 04:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
                    '2022-08-10 05:00:00+0000': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-11 04:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-17 04:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-09-10 04:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                },
                day: {
                    '2022-08-10 00:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
                    '2022-08-11 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-17 00:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-09-10 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                },
                // week and month charts bucket annotations per day — not per week/month — so that
                // e.g. an annotation on Dec 1 and an annotation on Dec 15 don't collapse into one badge.
                week: {
                    '2022-08-10 00:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
                    '2022-08-11 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-17 00:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-09-10 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                },
                month: {
                    '2022-08-10 00:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'UTC')),
                    '2022-08-11 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-08-17 00:00:00+0000': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                    '2022-09-10 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'UTC')
                    ),
                },
            },
            'America/Phoenix': {
                // Purposefully using Phoenix for test determinism - Arizona does NOT observe DST
                second: {
                    '2022-08-09 21:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED, MOCK_ANNOTATION_DASHBOARD_SCOPED].map(
                        (annotation) => deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-09 21:00:01-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-09 21:01:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-09 22:00:00-0700': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-10 21:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-16 21:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-09-09 21:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                },
                minute: {
                    '2022-08-09 21:00:00-0700': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'America/Phoenix')),
                    '2022-08-09 21:01:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-09 22:00:00-0700': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-10 21:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-16 21:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-09-09 21:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                },
                hour: {
                    '2022-08-09 21:00:00-0700': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'America/Phoenix')),
                    '2022-08-09 22:00:00-0700': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-10 21:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-16 21:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-09-09 21:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                },
                day: {
                    '2022-08-09 00:00:00-0700': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'America/Phoenix')),
                    '2022-08-10 00:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-16 00:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-09-09 00:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                },
                // week and month charts bucket per day — see UTC block above.
                week: {
                    '2022-08-09 00:00:00-0700': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'America/Phoenix')),
                    '2022-08-10 00:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-16 00:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-09-09 00:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                },
                month: {
                    '2022-08-09 00:00:00-0700': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'America/Phoenix')),
                    '2022-08-10 00:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-08-16 00:00:00-0700': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                    '2022-09-09 00:00:00-0700': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'America/Phoenix')
                    ),
                },
            },
            'Europe/Moscow': {
                // Purposefully using Moscow for test determinism - Russia does NOT observe DST
                second: {
                    '2022-08-10 07:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED, MOCK_ANNOTATION_DASHBOARD_SCOPED].map(
                        (annotation) => deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-10 07:00:01+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-10 07:01:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-10 08:00:00+0300': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-11 07:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-17 07:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-09-10 07:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                },
                minute: {
                    '2022-08-10 07:00:00+0300': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'Europe/Moscow')),
                    '2022-08-10 07:01:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-10 08:00:00+0300': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-11 07:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-17 07:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-09-10 07:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                },
                hour: {
                    '2022-08-10 07:00:00+0300': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'Europe/Moscow')),
                    '2022-08-10 08:00:00+0300': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-11 07:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-17 07:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-09-10 07:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                },
                day: {
                    '2022-08-10 00:00:00+0300': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'Europe/Moscow')),
                    '2022-08-11 00:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-17 00:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-09-10 00:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                },
                // week and month charts bucket per day — see UTC block above.
                week: {
                    '2022-08-10 00:00:00+0300': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'Europe/Moscow')),
                    '2022-08-11 00:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-17 00:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-09-10 00:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                },
                month: {
                    '2022-08-10 00:00:00+0300': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, 'Europe/Moscow')),
                    '2022-08-11 00:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-08-17 00:00:00+0300': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                    '2022-09-10 00:00:00+0300': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3].map((annotation) =>
                        deserializeAnnotation(annotation, 'Europe/Moscow')
                    ),
                },
            },
        }

        for (const [timezone, intervalAndExpectedGroupings] of Object.entries(
            EXPECTED_GROUPINGS_BY_INTERVAL_AND_TIMEZONE
        )) {
            for (const [interval, expectedGrouping] of Object.entries(intervalAndExpectedGroupings)) {
                it(`groups correctly by ${interval} with ${timezone} as insight timezone`, async () => {
                    initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })

                    useInsightMocks(interval, timezone)

                    logic = annotationsOverlayLogic({
                        dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                        insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                        dashboardId: MOCK_DASHBOARD_ID,
                        dates: ['2022-01-01', '2023-01-01'],
                        ticks: [{ value: 0 }, { value: 1 }],
                    })
                    logic.mount()
                    await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
                    await expectLogic(
                        insightLogic({ dashboardItemId: MOCK_INSIGHT_SHORT_ID, dashboardId: MOCK_DASHBOARD_ID })
                    ).toDispatchActions(['loadInsightSuccess'])
                    await expectLogic(logic).toMatchValues({
                        groupedAnnotations: expectedGrouping,
                    })
                })
            }
        }

        it(`does not merge day groups even when Chart.js renders only one tick per N days (UTC)`, async () => {
            // On a daily chart where Chart.js decides to render sparse ticks (e.g. one tick every 2 days),
            // annotation grouping should still be per-day — not bucketed by tick spacing.
            useInsightMocks()

            logic = annotationsOverlayLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                dates: ['2022-08-10', '2022-08-11', '2022-08-12'],
                ticks: [
                    { value: 0 },
                    { value: 2 }, // One tick per 2 days — used to cause annotations to be merged
                ],
                dashboardId: MOCK_DASHBOARD_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(
                insightLogic({ dashboardItemId: MOCK_INSIGHT_SHORT_ID, dashboardId: MOCK_DASHBOARD_ID })
            ).toDispatchActions(['loadInsightSuccess'])
            await expectLogic(logic).toMatchValues({
                groupedAnnotations: {
                    '2022-08-10 00:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, MOCK_DEFAULT_TEAM.timezone)),
                    '2022-08-11 00:00:00+0000': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1].map((annotation) =>
                        deserializeAnnotation(annotation, MOCK_DEFAULT_TEAM.timezone)
                    ),
                },
            })
        })

        it(`does not merge hour groups even when Chart.js renders only one tick per N hours (UTC)`, async () => {
            useInsightMocks('hour')

            logic = annotationsOverlayLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                dates: ['2022-08-10 04:00', '2022-08-10 05:00', '2022-08-10 06:00', '2022-08-10 07:00'],
                ticks: [
                    { value: 0 },
                    { value: 2 }, // One tick per 2 hours — used to cause annotations to be merged
                ],
                dashboardId: MOCK_DASHBOARD_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(
                insightLogic({ dashboardItemId: MOCK_INSIGHT_SHORT_ID, dashboardId: MOCK_DASHBOARD_ID })
            ).toDispatchActions(['loadInsightSuccess'])
            await expectLogic(logic).toMatchValues({
                groupedAnnotations: {
                    '2022-08-10 04:00:00+0000': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_DASHBOARD_SCOPED,
                    ].map((annotation) => deserializeAnnotation(annotation, MOCK_DEFAULT_TEAM.timezone)),
                    '2022-08-10 05:00:00+0000': [MOCK_ANNOTATION_INSIGHT_1_SCOPED].map((annotation) =>
                        deserializeAnnotation(annotation, MOCK_DEFAULT_TEAM.timezone)
                    ),
                },
            })
        })
    })

    describe('annotationBadgeDataIndices', () => {
        it.each<{ interval: IntervalType; dates: string[]; expected: Record<string, number> }>([
            {
                interval: 'month',
                dates: ['2022-08-01', '2022-09-01', '2022-10-01'],
                expected: { '2022-08-10 00:00:00+0000': 9 / 31, '2022-09-10 00:00:00+0000': 1 + 9 / 30 },
            },
            {
                // Regression: dayjs week starts Sunday, would drift Monday-aligned dates back 1 day.
                interval: 'week',
                dates: ['2022-08-08', '2022-08-15', '2022-08-22', '2022-08-29', '2022-09-05', '2022-09-12'],
                expected: { '2022-08-10 00:00:00+0000': 2 / 7, '2022-09-10 00:00:00+0000': 4 + 5 / 7 },
            },
        ])('$interval chart → fractional indices', async ({ interval, dates, expected }) => {
            useInsightMocks(interval)
            logic = annotationsOverlayLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                dates,
                ticks: dates.map((_, i) => ({ value: i })),
                dashboardId: MOCK_DASHBOARD_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(
                insightLogic({ dashboardItemId: MOCK_INSIGHT_SHORT_ID, dashboardId: MOCK_DASHBOARD_ID })
            ).toDispatchActions(['loadInsightSuccess'])

            for (const b of logic.values.annotationBadgeDataIndices as { dateKey: string; dataIndex: number }[]) {
                if (expected[b.dateKey] !== undefined) {
                    expect(b.dataIndex).toBeCloseTo(expected[b.dateKey], 5)
                }
            }
        })
    })
})
