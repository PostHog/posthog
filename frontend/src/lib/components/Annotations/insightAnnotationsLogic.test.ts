import { expectLogic } from 'kea-test-utils'
import { annotationsPageLogic } from 'scenes/annotations/annotationsPageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnnotationScope, AnnotationType, InsightShortId, IntervalType } from '~/types'
import { insightAnnotationsLogic } from './insightAnnotationsLogic'

const MOCK_INSIGHT_SHORT_ID = 'abcdef' as InsightShortId
const MOCK_INSIGHT_NUMERIC_ID = 1

const BASE_MOCK_ANNOTATION = {
    creation_type: 'USR',
    created_by: {
        id: 5,
        uuid: '0182cb27-8dfc-0000-1f45-c16dc0de95ea',
        distinct_id: 'XoBG3ygtKV8635pAFkEWHKboT6me1MTVaJETde7dm8V',
        first_name: 'Employee 427',
        email: 'michael@posthog.com',
    },
    created_at: '2022-08-26T12:06:00.892304Z',
    updated_at: '2022-08-29T11:21:25.022540Z',
    deleted: false,
}

const MOCK_ANNOTATION_ORG_SCOPED: AnnotationType = {
    id: 20,
    content: 'Alpha',
    date_marker: '2022-08-10T12:00:00.000000Z',
    dashboard_item: null,
    insight_short_id: null,
    insight_name: null,
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3: AnnotationType = {
    id: 10,
    content: 'Alpha',
    date_marker: '2022-08-10T12:00:01.000000Z', // A second after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_PROJECT_SCOPED: AnnotationType = {
    id: 17,
    content: 'Beta',
    date_marker: '2022-08-10T12:01:00.000000Z', // A minute after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: null,
    insight_short_id: null,
    insight_name: null,
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_INSIGHT_1_SCOPED: AnnotationType = {
    id: 19,
    content: 'Theta',
    date_marker: '2022-08-10T13:00:00.000000Z', // An hour after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 1,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    scope: AnnotationScope.Insight,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1: AnnotationType = {
    id: 20,
    content: 'Theta',
    date_marker: '2022-08-11T12:00:00.000000Z', // A day after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_INSIGHT_3_SCOPED: AnnotationType = {
    id: 21,
    content: 'Omega',
    date_marker: '2022-08-17T12:00:00.000000Z', // A week after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    scope: AnnotationScope.Insight,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1: AnnotationType = {
    id: 40,
    content: 'Alpha',
    date_marker: '2022-08-17T12:00:00.000000Z', // A week after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
const MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3: AnnotationType = {
    id: 22,
    content: 'Omega',
    date_marker: '2022-09-10T12:00:00.000000Z', // A month after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}

describe('insightAnnotationsLogic', () => {
    let logic: ReturnType<typeof insightAnnotationsLogic.build>

    beforeEach(() => {
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
                    ],
                },
            },
        })
        initKeaTests()
    })

    it('loads annotations on mount', async () => {
        logic = insightAnnotationsLogic({
            dashboardItemId: MOCK_INSIGHT_SHORT_ID,
            insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
        })
        logic.mount()
        await expectLogic(annotationsPageLogic).toDispatchActions(['loadAnnotations'])
    })

    describe('relevantAnnotations', () => {
        it('returns annotations scoped to the insight for a saved insight', async () => {
            logic = insightAnnotationsLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
            })
            logic.mount()
            await expectLogic(annotationsPageLogic).toDispatchActions(['loadAnnotationsSuccess'])
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
                ],
            })
        })

        it('returns annotations scoped to the project for a new insight', async () => {
            logic = insightAnnotationsLogic({ dashboardItemId: 'new', insightNumericId: 'new' })
            logic.mount()
            await expectLogic(annotationsPageLogic).toDispatchActions(['loadAnnotationsSuccess'])
            await expectLogic(logic).toMatchValues({
                relevantAnnotations: [
                    // The annotation scoped to insight 3 should be omitted
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3,
                ],
            })
        })
    })

    describe('groupedAnnotations', () => {
        const INTERVAL_WITH_EXPECTED_GROUPING: Record<IntervalType, Record<string, AnnotationType[]>> = {
            hour: {
                '2022-08-10 12': [
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                ],
                '2022-08-10 13': [MOCK_ANNOTATION_INSIGHT_1_SCOPED],
                '2022-08-11 12': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1],
                '2022-08-17 12': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                '2022-09-10 12': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
            },
            day: {
                '2022-08-10': [
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                ],
                '2022-08-11': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1],
                '2022-08-17': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                '2022-09-10': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
            },
            week: {
                '2022-08-07': [
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                ],
                '2022-08-14': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                '2022-09-04': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
            },
            month: {
                '2022-08': [
                    MOCK_ANNOTATION_ORG_SCOPED,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                    MOCK_ANNOTATION_PROJECT_SCOPED,
                    MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                    MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1,
                    MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1,
                ],
                '2022-09': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
            },
        }

        for (const [interval, expectedGrouping] of Object.entries(INTERVAL_WITH_EXPECTED_GROUPING)) {
            it(`groups correctly by ${interval}`, async () => {
                useMocks({
                    get: {
                        '/api/projects/:team/insights/': () => {
                            return [
                                200,
                                {
                                    results: [
                                        {
                                            result: null,
                                            id: 1,
                                            short_id: MOCK_INSIGHT_SHORT_ID,
                                            filters: {
                                                interval,
                                            },
                                        },
                                    ],
                                },
                            ]
                        },
                    },
                })

                logic = insightAnnotationsLogic({
                    dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                    insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                })
                logic.mount()
                await expectLogic(annotationsPageLogic).toDispatchActions(['loadAnnotationsSuccess'])
                await expectLogic(insightLogic({ dashboardItemId: MOCK_INSIGHT_SHORT_ID })).toDispatchActions([
                    'loadInsightSuccess',
                ])
                await expectLogic(logic).toMatchValues({
                    groupedAnnotations: expectedGrouping,
                })
            })
        }
    })
})
