import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import { makeTestSetup } from 'lib/components/ActivityLog/activityLogLogic.test.setup'

describe('the activity log logic', () => {
    describe('humanizing plugins', () => {
        const pluginTestSetup = makeTestSetup(ActivityScope.PLUGIN, '/api/organizations/@current/plugins/activity')
        it('can handle installation of a plugin', async () => {
            const logic = await pluginTestSetup('the installed plugin', 'installed', null)
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter installed the app: the installed plugin'
            )
        })

        it('can handle un-installation of a plugin', async () => {
            const logic = await pluginTestSetup('the removed plugin', 'uninstalled', null)
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter uninstalled the app: the removed plugin'
            )
        })

        it('can handle enabling a plugin', async () => {
            const logic = await pluginTestSetup('the removed plugin', 'enabled', [
                {
                    type: 'Plugin',
                    action: 'created',
                    field: 'name',
                    after: 'world',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter enabled the app: the removed plugin with config ID 7, with field name set to world'
            )
        })

        it('can handle enabling a plugin with a secret value', async () => {
            const logic = await pluginTestSetup('the removed plugin', 'enabled', [
                {
                    type: 'Plugin',
                    action: 'created',
                    field: 'name',
                    after: 'world',
                },
                {
                    type: 'Plugin',
                    action: 'created',
                    field: 'super secret password',
                    after: '**************** POSTHOG SECRET FIELD ****************',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter enabled the app: the removed plugin with config ID 7, with field name set to world, and field super secret password set to <secret_value>'
            )
        })

        it('can handle disabling a plugin', async () => {
            const logic = await pluginTestSetup('the removed plugin', 'disabled', [
                {
                    type: 'Plugin',
                    action: 'created',
                    field: 'name',
                    after: 'world',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter disabled the app: the removed plugin with config ID 7'
            )
        })

        it('can handle config_update ', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'config_updated', [
                {
                    type: 'Plugin',
                    action: 'created',
                    field: 'first example',
                    after: 'added this config',
                },

                {
                    type: 'Plugin',
                    action: 'deleted',
                    field: 'second example',
                    before: 'removed this config',
                },

                {
                    type: 'Plugin',
                    action: 'changed',
                    field: 'third example',
                    before: 'changed from this config',
                    after: 'to this new config',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter added new field first example" with value added this config, removed field second example, which had value removed this config, and updated field third example from value changed from this config to value to this new config on app the changed plugin with config ID 7.'
            )
        })

        it('can handle exports starting', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'job_triggered', null, null, {
                job_id: '123',
                job_type: 'Export historical events V2',
                payload: {
                    dateRange: ['2022-09-05', '2022-09-07'],
                },
            })
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter started exporting historical events between 2022-09-05 and 2022-09-07 (inclusive).'
            )
        })

        it('can handle some other job starting', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'job_triggered', null, null, {
                job_id: '123',
                job_type: 'someJob',
                payload: {
                    foo: 'bar',
                },
            })
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter triggered job: someJob with config ID 7.'
            )
            expect(render(<>{actual[0].extendedDescription}</>).container).toHaveTextContent(
                'Payload: { "foo": "bar" }'
            )
        })

        it('can handle exports finishing', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'export_success', null, null, {
                job_id: '123',
                job_type: 'Export historical events V2',
                payload: {
                    id: 1,
                    parallelism: 3,
                    dateFrom: '2021-10-29T00:00:00.000Z',
                    dateTo: '2021-11-05T00:00:00.000Z',
                },
            })
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'Finished exporting historical events between 2021-10-29 and 2021-11-04 (inclusive).'
            )
        })

        it('can handle exports failing', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'export_fail', null, null, {
                job_id: '123',
                job_type: 'Export historical events V2',
                payload: {
                    id: 1,
                    parallelism: 3,
                    dateFrom: '2021-10-29T00:00:00.000Z',
                    dateTo: '2021-11-05T00:00:00.000Z',
                },
            })
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'Fatal error exporting historical events between 2021-10-29 and 2021-11-04 (inclusive). Check logs for more details.'
            )
        })

        it('can handle new plugin attachments', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'attachment_created', [
                {
                    type: 'PluginConfig',
                    action: 'created',
                    field: undefined,
                    before: undefined,
                    after: 'attachment.txt',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter attached a file attachment.txt on app: the changed plugin with config ID 7'
            )
        })

        it('can handle updated plugin attachments', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'attachment_updated', [
                {
                    type: 'PluginConfig',
                    action: 'changed',
                    field: undefined,
                    before: 'attachment.txt',
                    after: 'attachment.txt',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter updated attached file attachment.txt on app: the changed plugin with config ID 7'
            )
        })

        it('can handle renamed plugin attachments', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'attachment_updated', [
                {
                    type: 'PluginConfig',
                    action: 'changed',
                    field: undefined,
                    before: 'attachment1.txt',
                    after: 'attachment2.txt',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter updated attached file from attachment1.txt to attachment2.txt on app: the changed plugin with config ID 7'
            )
        })

        it('can handle deleted plugin attachments', async () => {
            const logic = await pluginTestSetup('the changed plugin', 'attachment_deleted', [
                {
                    type: 'PluginConfig',
                    action: 'deleted',
                    field: undefined,
                    before: 'attachment.txt',
                    after: undefined,
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter deleted attached file attachment.txt on app: the changed plugin with config ID 7'
            )
        })
    })
})
