import { expectLogic } from 'kea-test-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useMocks } from '~/mocks/jest'
import { annotationsModel } from '~/models/annotationsModel'
import { initKeaTests } from '~/test/init'
import { AnnotationScope, AnnotationType, InsightShortId, IntervalType } from '~/types'
import { insightAnnotationsLogic } from './insightAnnotationsLogic'

jest.spyOn(Storage.prototype, 'getItem')

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

/** ID 20 at 2022-08-10T04:00:00.000000Z */
const MOCK_ANNOTATION_ORG_SCOPED: AnnotationType = {
    id: 20,
    content: 'Alpha',
    date_marker: '2022-08-10T04:00:00.000000Z',
    dashboard_item: null,
    insight_short_id: null,
    insight_name: null,
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 10 at 2022-08-10T04:00:01.000000Z */
const MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3: AnnotationType = {
    id: 10,
    content: 'Alpha',
    date_marker: '2022-08-10T04:00:01.000000Z', // A second after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 17 at 2022-08-10T04:01:00.000000Z */
const MOCK_ANNOTATION_PROJECT_SCOPED: AnnotationType = {
    id: 17,
    content: 'Beta',
    date_marker: '2022-08-10T04:01:00.000000Z', // A minute after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: null,
    insight_short_id: null,
    insight_name: null,
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 19 at 2022-08-10T05:00:00.000000Z */
const MOCK_ANNOTATION_INSIGHT_1_SCOPED: AnnotationType = {
    id: 19,
    content: 'Theta',
    date_marker: '2022-08-10T05:00:00.000000Z', // An hour after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 1,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    scope: AnnotationScope.Insight,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 20 at 2022-08-11T04:00:00.000000Z */
const MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1: AnnotationType = {
    id: 20,
    content: 'Theta',
    date_marker: '2022-08-11T04:00:00.000000Z', // A day after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 21 at 2022-08-17T04:00:00.000000Z */
const MOCK_ANNOTATION_INSIGHT_3_SCOPED: AnnotationType = {
    id: 21,
    content: 'Omega',
    date_marker: '2022-08-17T04:00:00.000000Z', // A week after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    scope: AnnotationScope.Insight,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 40 at 2022-08-17T04:00:00.000000Z */
const MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1: AnnotationType = {
    id: 40,
    content: 'Alpha',
    date_marker: '2022-08-17T04:00:00.000000Z', // A week after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: MOCK_INSIGHT_NUMERIC_ID,
    insight_short_id: MOCK_INSIGHT_SHORT_ID,
    insight_name: 'Pageviews',
    scope: AnnotationScope.Organization,
    ...BASE_MOCK_ANNOTATION,
}
/** ID 22 at 2022-09-10T04:00:00.000000Z */
const MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3: AnnotationType = {
    id: 22,
    content: 'Omega',
    date_marker: '2022-09-10T04:00:00.000000Z', // A month after MOCK_ANNOTATION_ORG_SCOPED
    dashboard_item: 3,
    insight_short_id: 'xxxxxx' as InsightShortId,
    insight_name: 'Clicks',
    scope: AnnotationScope.Project,
    ...BASE_MOCK_ANNOTATION,
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
function useInsightMock(interval: string = 'day', timezone: string = 'UTC') {
    const insight = {
        result: {},
        id: MOCK_INSIGHT_NUMERIC_ID,
        short_id: MOCK_INSIGHT_SHORT_ID,
        filters: {
            interval,
        },
        timezone,
    }
    useMocks({
        get: {
            '/api/projects/:team_id/insights/': () => {
                return [
                    200,
                    {
                        results: [insight],
                    },
                ]
            },
            [`/api/projects/:team_id/insights/${MOCK_INSIGHT_NUMERIC_ID}`]: () => {
                return [200, insight]
            },
        },
    })
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
        useInsightMock()

        logic = insightAnnotationsLogic({
            dashboardItemId: MOCK_INSIGHT_SHORT_ID,
            insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
        })
        logic.mount()
        await expectLogic(annotationsModel).toDispatchActions(['loadAnnotations'])
    })

    describe('relevantAnnotations', () => {
        it('returns annotations scoped to the insight for a saved insight', async () => {
            useInsightMock()

            logic = insightAnnotationsLogic({
                dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
            })
            logic.mount()
            await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
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
            useInsightMock()

            logic = insightAnnotationsLogic({ dashboardItemId: 'new', insightNumericId: 'new' })
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
                ],
            })
        })
    })

    describe('groupedAnnotations', () => {
        const EXPECTED_GROUPINGS_BY_INTERVAL_AND_TIMEZONE: Record<
            string,
            Record<IntervalType, Record<string, AnnotationType[]>>
        > = {
            UTC: {
                hour: {
                    '2022-08-10 04': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                    ],
                    '2022-08-10 05': [MOCK_ANNOTATION_INSIGHT_1_SCOPED],
                    '2022-08-11 04': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1],
                    '2022-08-17 04': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                    '2022-09-10 04': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
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
            },
            'America/Phoenix': {
                // Purposefully using Phoenix for test determinism - Arizona does NOT observe DST
                hour: {
                    '2022-08-09 21': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                    ],
                    '2022-08-09 22': [MOCK_ANNOTATION_INSIGHT_1_SCOPED],
                    '2022-08-10 21': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1],
                    '2022-08-16 21': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                    '2022-09-09 21': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
                },
                day: {
                    '2022-08-09': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                        MOCK_ANNOTATION_INSIGHT_1_SCOPED,
                    ],
                    '2022-08-10': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1],
                    '2022-08-16': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                    '2022-09-09': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
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
            },
            'Europe/Moscow': {
                // Purposefully using Moscow for test determinism - Russia does NOT observe DST
                hour: {
                    '2022-08-10 07': [
                        MOCK_ANNOTATION_ORG_SCOPED,
                        MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_3,
                        MOCK_ANNOTATION_PROJECT_SCOPED,
                    ],
                    '2022-08-10 08': [MOCK_ANNOTATION_INSIGHT_1_SCOPED],
                    '2022-08-11 07': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_1],
                    '2022-08-17 07': [MOCK_ANNOTATION_ORG_SCOPED_FROM_INSIGHT_1],
                    '2022-09-10 07': [MOCK_ANNOTATION_PROJECT_SCOPED_FROM_INSIGHT_3],
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
            },
        }

        for (const [timezone, intervalAndExpectedGroupings] of Object.entries(
            EXPECTED_GROUPINGS_BY_INTERVAL_AND_TIMEZONE
        )) {
            for (const [interval, expectedGrouping] of Object.entries(intervalAndExpectedGroupings)) {
                it(`groups correctly by ${interval} with ${timezone} as insight timezone`, async () => {
                    useInsightMock(interval, timezone)

                    logic = insightAnnotationsLogic({
                        dashboardItemId: MOCK_INSIGHT_SHORT_ID,
                        insightNumericId: MOCK_INSIGHT_NUMERIC_ID,
                    })
                    logic.mount()
                    await expectLogic(annotationsModel).toDispatchActions(['loadAnnotationsSuccess'])
                    await expectLogic(insightLogic({ dashboardItemId: MOCK_INSIGHT_SHORT_ID })).toDispatchActions([
                        'loadInsightSuccess',
                    ])
                    await expectLogic(logic).toMatchValues({
                        groupedAnnotations: expectedGrouping,
                    })
                })
            }
        }
    })
})
