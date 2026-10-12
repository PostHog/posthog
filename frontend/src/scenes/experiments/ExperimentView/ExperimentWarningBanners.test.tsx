import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { experimentLogic } from '../experimentLogic'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'

const EXPERIMENT_ID = 7

describe('ExperimentWarningBanner', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    beforeEach(() => {
        const emptyList = { count: 0, next: null, previous: null, results: [] }
        useMocks({
            get: {
                '/api/projects/:team/experiments': emptyList,
                '/api/projects/:team/experiment_holdouts': emptyList,
                '/api/projects/:team/experiment_saved_metrics': emptyList,
            },
        })
        initKeaTests()
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        { variantKey: 'test', expected: 'Variant "test" is rolled out to 100% of users.' },
        { variantKey: null, expected: 'One variant is rolled out to 100% of users.' },
    ])('names the shipped variant $variantKey', ({ variantKey, expected }) => {
        logic.actions.setExperiment({
            ...NEW_EXPERIMENT,
            id: EXPERIMENT_ID,
            status: ExperimentStatus.Running,
            start_date: dayjs().subtract(3, 'day').toISOString(),
            feature_flag: { id: 1, key: 'checkout-flag', active: true, filters: { groups: [] } },
            health: {
                findings: [
                    {
                        code: 'variant_shipped_while_running',
                        subcode: 'running_but_single_variant_shipped',
                        severity: 'warning',
                        title: '',
                        detail: '',
                        evidence: { variant_key: variantKey },
                        actions: [],
                        diagnostic_ref: null,
                    },
                ],
            },
        } as unknown as Experiment)

        const { container } = render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <ExperimentWarningBanner />
                </BindLogic>
            </Provider>
        )

        expect(container).toHaveTextContent(expected)
    })
})
