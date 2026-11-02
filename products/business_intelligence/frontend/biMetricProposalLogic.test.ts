import { LemonDialog } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as overwriteDialog from 'products/data_catalog/frontend/openOverwriteMetricDialog'

import { DEFAULT_BI_CONFIG } from './biEditorTypes'
import { biMetricProposalLogic } from './biMetricProposalLogic'

afterEach(() => jest.restoreAllMocks())

it.each(['overwrite', 'cancel', 'navigate'] as const)(
    'handles a metric name conflict with %s without losing the form or overwriting implicitly',
    async (choice) => {
        initKeaTests()
        const requests: Record<string, unknown>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/data_catalog/metrics/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    requests.push(body)
                    return body.overwrite
                        ? [201, { ...body, id: 'existing-metric', status: 'proposed' }]
                        : [
                              409,
                              {
                                  code: 'metric_name_taken',
                                  detail: 'Name already exists',
                                  extra: { existing_metric: { name: 'purchases', status: 'approved' } },
                              },
                          ]
                },
            },
        })
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        const open = jest.spyOn(LemonDialog, 'openForm').mockImplementation(() => undefined)
        const confirm = jest.spyOn(overwriteDialog, 'openOverwriteMetricDialog').mockImplementation((dialog) => {
            if (choice === 'overwrite') {
                dialog.onOverwrite()
            } else if (choice === 'cancel') {
                dialog.onCancel?.()
            } else {
                open.mock.calls[0][0].onAfterClose?.()
            }
        })
        const logic = biMetricProposalLogic({
            tabId: 'proposal-conflict',
            name: 'Purchases',
            config: DEFAULT_BI_CONFIG,
            snapshot: 'SELECT 7',
        })
        const unmount = logic.mount()
        try {
            logic.actions.proposeMetric()
            const form = open.mock.calls[0][0]
            const fields = {
                ...form.initialValues,
                name: 'purchases',
                description: 'Completed purchases.',
                unit: 'orders',
            }
            if (choice === 'overwrite') {
                await form.onSubmit(fields)
                expect(requests).toHaveLength(2)
                expect(requests[1]).toEqual({ ...requests[0], overwrite: true })
                expect(requests[1]).toMatchObject({
                    created_source: 'user',
                    unit: 'orders',
                    definition: { kind: 'HogQLQuery', query: 'SELECT 7' },
                })
            } else {
                await expect(form.onSubmit(fields)).rejects.toBeDefined()
                expect(requests).toHaveLength(1)
                confirm.mockImplementation((dialog) => dialog.onOverwrite())
                await form.onSubmit(fields)
                expect(requests).toHaveLength(choice === 'navigate' ? 1 : 3)
            }
            expect(confirm).toHaveBeenCalledWith(
                expect.objectContaining({ existing: { name: 'purchases', status: 'approved' } })
            )
            expect(toast).not.toHaveBeenCalled()
        } finally {
            unmount()
        }
    }
)

it('does not open an overwrite prompt when a conflict arrives after the form closes', async () => {
    initKeaTests()
    let releaseRequest!: () => void
    const pending = new Promise<void>((resolve) => {
        releaseRequest = resolve
    })
    const create = jest.fn(async () => {
        await pending
        return [
            409,
            {
                code: 'metric_name_taken',
                detail: 'Name already exists',
                extra: { existing_metric: { name: 'purchases', status: 'approved' } },
            },
        ]
    })
    useMocks({ post: { '/api/projects/:team_id/data_catalog/metrics/': create } })
    const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
    const open = jest.spyOn(LemonDialog, 'openForm').mockImplementation(() => undefined)
    const confirm = jest.spyOn(overwriteDialog, 'openOverwriteMetricDialog')
    const logic = biMetricProposalLogic({
        tabId: 'closed-proposal',
        name: 'Purchases',
        config: DEFAULT_BI_CONFIG,
        snapshot: 'SELECT 7',
    })
    const unmount = logic.mount()
    try {
        logic.actions.proposeMetric()
        const form = open.mock.calls[0][0]
        const submission = form.onSubmit({
            ...form.initialValues,
            name: 'purchases',
            description: 'Completed purchases.',
        })
        form.onAfterClose?.()
        releaseRequest()
        await expect(submission).rejects.toBeDefined()
        expect(create).toHaveBeenCalledTimes(1)
        expect(confirm).not.toHaveBeenCalled()
        expect(toast).not.toHaveBeenCalled()
    } finally {
        unmount()
    }
})

it('shows a failed proposal and allows retrying the same form', async () => {
    initKeaTests()
    let attempts = 0
    useMocks({
        post: {
            '/api/projects/:team_id/data_catalog/metrics/': async ({ request }) => {
                attempts++
                return attempts === 1
                    ? [400, { detail: 'Definition could not be saved.' }]
                    : [
                          201,
                          {
                              ...((await request.json()) as Record<string, unknown>),
                              id: 'retry-metric',
                              status: 'proposed',
                          },
                      ]
            },
        },
    })
    const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
    const open = jest.spyOn(LemonDialog, 'openForm').mockImplementation(() => undefined)
    const logic = biMetricProposalLogic({
        tabId: 'proposal-retry',
        name: 'Purchases',
        config: DEFAULT_BI_CONFIG,
        snapshot: 'SELECT 7',
    })
    const unmount = logic.mount()
    try {
        logic.actions.proposeMetric()
        const form = open.mock.calls[0][0]
        const fields = { ...form.initialValues, name: 'purchases', description: 'Completed purchases.' }
        await expect(form.onSubmit(fields)).rejects.toBeDefined()
        expect(toast).toHaveBeenCalledWith('Definition could not be saved.')
        await expect(form.onSubmit(fields)).resolves.toBeUndefined()
        expect(attempts).toBe(2)
    } finally {
        unmount()
    }
})

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
