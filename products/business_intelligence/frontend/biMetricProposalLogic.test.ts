import { LemonDialog } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_BI_CONFIG } from './biEditorTypes'
import { biMetricProposalLogic } from './biMetricProposalLogic'

afterEach(() => jest.restoreAllMocks())

it('validates an initializing form and submits one fixed snapshot while a request is pending', async () => {
    initKeaTests()
    let releaseRequest!: () => void
    const pending = new Promise<void>((resolve) => {
        releaseRequest = resolve
    })
    const create = jest.fn(async ({ request }: { request: Request }) => {
        const body = await request.json()
        await pending
        return [201, { ...body, id: 'metric-example', status: 'proposed' }]
    })
    useMocks({ post: { '/api/projects/:team_id/data_catalog/metrics/': create } })
    const open = jest.spyOn(LemonDialog, 'openForm').mockImplementation(() => undefined)
    const logic = biMetricProposalLogic({
        tabId: 'proposal-test',
        name: 'Weekly purchases',
        config: DEFAULT_BI_CONFIG,
        snapshot: 'SELECT 42 LIMIT 1000',
    })
    logic.mount()
    logic.actions.proposeMetric()
    const form = open.mock.calls[0][0]
    expect(form.errors?.name(undefined, {})).toBeTruthy()
    expect(form.errors?.description(undefined, {})).toBeTruthy()
    const fields = { ...form.initialValues, name: 'weekly_purchases', description: 'Purchases in this date window.' }
    const submissions = Promise.all([form.onSubmit(fields), form.onSubmit(fields)])
    releaseRequest()
    await submissions
    expect(create).toHaveBeenCalledTimes(1)
    const result = await create.mock.results[0].value
    expect(result[1]).toMatchObject({
        name: 'weekly_purchases',
        display_name: 'Weekly purchases',
        definition: { kind: 'HogQLQuery', query: 'SELECT 42 LIMIT 1000' },
    })
    logic.unmount()
})
