import { MOCK_DEFAULT_ORGANIZATION, MOCK_SECOND_ORGANIZATION_MEMBER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlType, AvailableFeature } from '~/types'

import { accessControlLogic } from './accessControlLogic'
import { AccessControlObject } from './AccessControlObject'
import { QuillAccessControlObject } from './quill/QuillAccessControlObject'

const props = { resource: 'dashboard' as const, resource_id: '123', title: 'Dashboard access', description: '' }

describe('object access overrides', () => {
    let logic: ReturnType<typeof accessControlLogic.build>
    let accessControls: AccessControlType[]
    const save = jest.fn()

    beforeEach(() => {
        accessControls = []
        save.mockClear()
        useMocks({
            get: {
                '/api/projects/:id/dashboards/123/access_controls': () => [
                    200,
                    {
                        access_controls: accessControls,
                        available_access_levels: ['none', 'viewer', 'editor', 'manager'],
                        default_access_level: 'editor',
                        minimum_access_level: 'none',
                        user_access_level: 'manager',
                        user_can_edit_access_levels: true,
                    },
                ],
                '/api/organizations/:id/roles/': { results: [{ id: 'analysts', name: 'Analysts', members: [] }] },
            },
            put: {
                '/api/projects/:id/dashboards/123/access_controls': async ({ request }) => {
                    const body = await request.json()
                    save(body)
                    accessControls = [{ ...body, resource: 'dashboard', resource_id: '123' }]
                    return [200, body]
                },
            },
        })
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: [AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS].map(
                (key) => ({ key, name: key })
            ),
        })
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        ['Lemon member', AccessControlObject, 0, 'Rose', { organization_member: MOCK_SECOND_ORGANIZATION_MEMBER.id }],
        ['Lemon role', AccessControlObject, 1, 'Analysts', { role: 'analysts' }],
        [
            'Quill member',
            QuillAccessControlObject,
            0,
            'Rose',
            { organization_member: MOCK_SECOND_ORGANIZATION_MEMBER.id },
        ],
        ['Quill role', QuillAccessControlObject, 1, 'Analysts', { role: 'analysts' }],
    ] as const)('%s can add and edit a No access override', async (_, Component, index, name, subject) => {
        const user = userEvent.setup()
        logic = accessControlLogic.build(props)
        await expectLogic(logic, () => logic.mount()).toDispatchActions(['loadAccessControlsSuccess'])
        render(<Component {...props} />)
        await waitFor(() =>
            expect(screen.getAllByText('Add')[index].closest('button')).toHaveAttribute('aria-disabled', 'false')
        )
        fireEvent.click(screen.getAllByText('Add')[index].closest('button')!)
        const dialog = within(await screen.findByRole('dialog'))
        await user.click(dialog.getByText('Viewer'))
        await user.click(await screen.findByText('No access'))
        expect(dialog.getByText('No access')).toBeVisible()
        await user.type(
            dialog.getByPlaceholderText(index === 0 ? 'Search for team members to add…' : 'Search for roles to add…'),
            name.slice(0, 3)
        )
        await user.click(await screen.findByText(name, { exact: true }))
        await user.click(dialog.getByText('Add', { exact: true }))
        await waitFor(() => expect(save).toHaveBeenCalledWith({ ...subject, access_level: 'none' }))
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
        await user.click(screen.getByText('No access'))
        await user.click(await screen.findByText('Viewer', { exact: true }))
        await waitFor(() => expect(save).toHaveBeenLastCalledWith({ ...subject, access_level: 'viewer' }))
    })
})
