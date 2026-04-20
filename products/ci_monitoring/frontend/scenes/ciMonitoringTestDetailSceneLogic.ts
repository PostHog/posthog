import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { ciMonitoringTestsExecutionsList, ciMonitoringTestsRetrieve } from '../generated/api'
import type { TestCaseApi, TestExecutionApi } from '../generated/api.schemas'
import type { ciMonitoringTestDetailSceneLogicType } from './ciMonitoringTestDetailSceneLogicType'

export interface CIMonitoringTestDetailSceneLogicProps {
    testId: string
}

export const ciMonitoringTestDetailSceneLogic = kea<ciMonitoringTestDetailSceneLogicType>([
    path(['products', 'ci_monitoring', 'frontend', 'scenes', 'ciMonitoringTestDetailSceneLogic']),
    props({} as CIMonitoringTestDetailSceneLogicProps),
    key((props) => props.testId),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    loaders(({ props, values }) => ({
        testCase: [
            null as TestCaseApi | null,
            {
                loadTestCase: async () => {
                    return await ciMonitoringTestsRetrieve(String(values.currentProjectId), props.testId)
                },
            },
        ],
        executions: [
            [] as TestExecutionApi[],
            {
                loadExecutions: async () => {
                    const response = await ciMonitoringTestsExecutionsList(
                        String(values.currentProjectId),
                        props.testId
                    )
                    return response.results
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.testCase],
            (testCase): Breadcrumb[] => [
                {
                    key: 'ci_monitoring',
                    name: 'CI monitoring',
                    path: '/ci_monitoring',
                },
                {
                    key: 'ci_monitoring_test',
                    name: testCase?.identifier || 'Test',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadTestCase()
        actions.loadExecutions()
    }),
])
