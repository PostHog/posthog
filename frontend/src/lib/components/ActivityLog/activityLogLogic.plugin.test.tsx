import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import React from 'react'
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
    })
})
