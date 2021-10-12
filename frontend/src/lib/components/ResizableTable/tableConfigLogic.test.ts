import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { UserType } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'

import api from 'lib/api'
jest.mock('lib/api')

const fakeUser: UserType = {
    id: 2,
    realm: 'cloud',
    date_joined: '2021-09-20T10:18:31.844574Z',
    uuid: '017c02b6-e024-0000-8856-60c4fb28ef07',
    distinct_id: 'GPIJ7YBYzERFjioLp1vGworK75sgwQoa95M1102U723',
    first_name: 'Testy McTesterson',
    email: 'testy@example.com',
    email_opt_in: true,
    anonymize_data: false,
    toolbar_mode: 'toolbar',
    has_password: true,
    is_staff: false,
    is_impersonated: false,
    team: {
        id: 1,
        uuid: '017c02b6-e072-0000-43ed-6f54c9c198a9',
        organization: '017c02b6-db59-0000-caa0-191cfa2db06a',
        api_token: 'phc_UIv80rdZrFGJyJJZ9q27MVkkx7OoDUeSZsrpHfDQ8F',
        name: 'Default Project',
        completed_snippet_onboarding: true,
        ingested_event: true,
        is_demo: false,
        timezone: 'UTC',
        access_control: false,
        effective_membership_level: 15,
    },
    organization: {
        id: '017c02b6-db59-0000-caa0-191cfa2db06a',
        name: 'testing locally',
        created_at: '2021-09-20T10:18:30.619585Z',
        updated_at: '2021-09-20T10:18:30.619605Z',
        membership_level: 15,
        personalization: {},
        setup: { is_active: false, current_section: null },
        setup_section_2_completed: true,
        plugins_access_level: 9,
        teams: [
            {
                id: 1,
                uuid: '017c02b6-e072-0000-43ed-6f54c9c198a9',
                organization: '017c02b6-db59-0000-caa0-191cfa2db06a',
                api_token: 'phc_UIv80rdZrFGJyJJZ9q27MVkkx7OoDUeSZsrpHfDQ8F',
                name: 'Default Project',
                completed_snippet_onboarding: true,
                ingested_event: true,
                is_demo: false,
                timezone: 'UTC',
                access_control: false,
                effective_membership_level: 15,
            },
        ],
        available_features: [],
        domain_whitelist: [],
        is_member_join_email_enabled: true,
    },
    organizations: [{ id: '017c02b6-db59-0000-caa0-191cfa2db06a', name: 'testing locally' }],
    events_column_config: { active: 'DEFAULT' },
}

describe('tableConfigLogic', () => {
    let logic: ReturnType<typeof tableConfigLogic.build>
    let builtUserLogic: ReturnType<typeof userLogic.build>

    mockAPI(async ({ pathname, searchParams, method, data }) => {
        if (pathname === 'api/users/@me/' && method === 'get') {
            return fakeUser
        }
        if (pathname === 'api/users/@me/' && method === 'update') {
            fakeUser.events_column_config = data && data.events_column_config
            return fakeUser
        }
        throw new Error(`Unmocked ${method} fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
    })

    initKeaTestLogic({
        logic: tableConfigLogic,
        props: {},
        onLogic: (l) => {
            logic = l
            builtUserLogic = userLogic()
        },
    })

    it('starts with expected defaults', async () => {
        await expectLogic(logic).toMount(builtUserLogic).toMatchValues({
            columnConfigSaving: false,
            modalVisible: false,
            columnConfig: [],
            selectedColumns: 'DEFAULT',
            tableWidth: 7,
            hasColumnConfigToSave: false,
        })
    })

    describe('column config source', () => {
        it('reads from the URL when present', async () => {
            router.actions.push(router.values.location.pathname, { tableColumns: ['egg', 'beans', 'toast'] })
            await expectLogic(logic).toMatchValues({
                columnConfig: ['egg', 'beans', 'toast'],
                selectedColumns: ['egg', 'beans', 'toast'],
            })
        })
        it('does not save to user when reading from URL', async () => {
            router.actions.push(router.values.location.pathname, { tableColumns: ['egg', 'beans', 'toast'] })
            await expectLogic(logic)
            expect(api.update).not.toHaveBeenCalled()
        })
        it('reads from the user if the URL has no column settings', async () => {
            router.actions.push(router.values.location.pathname, {})
            await expectLogic(builtUserLogic, () => {
                builtUserLogic.actions.updateUser({ events_column_config: { active: ['soup', 'bread', 'greens'] } })
            })
            await expectLogic(logic).toMatchValues({
                columnConfig: [],
                selectedColumns: ['soup', 'bread', 'greens'],
            })
        })
        it('writes to the URL when column config changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.setColumnConfig(['soup', 'bread', 'greens'])
            })
            expect(router.values.searchParams).toHaveProperty('tableColumns', ['soup', 'bread', 'greens'])
        })

        it('does not show a "save column layout as default" button in the modal when the URL and user match', async () => {
            await expectLogic(logic, () => {
                builtUserLogic.actions.updateUser({ events_column_config: { active: ['soup', 'bread', 'greens'] } })
                logic.actions.setColumnConfig(['soup', 'bread', 'greens'])
            }).toMatchValues({
                hasColumnConfigToSave: false,
            })
        })

        it('shows a "save column layout as default" button in the modal when the URL and don\'t user match', async () => {
            await expectLogic(logic, () => {
                builtUserLogic.actions.updateUser({ events_column_config: { active: ['soup', 'bread', 'greens'] } })
                logic.actions.setColumnConfig(['soup', 'bread', 'tea'])
            }).toMatchValues({
                hasColumnConfigToSave: true,
            })
        })

        it('sets column config when user update succeeds', async () => {
            await expectLogic(logic, () => {
                builtUserLogic.actions.updateUser({ events_column_config: { active: ['soup', 'bread', 'greens'] } })
            })
                .delay(0) // allow listeners to process API response
                .toMatchValues({
                    columnConfig: ['soup', 'bread', 'greens'],
                })
        })
    })

    it('can set modal visible', async () => {
        await expectLogic(logic, () => logic.actions.setModalVisible(true)).toMatchValues({
            modalVisible: true,
        })
    })

    it('can set column config saving', async () => {
        await expectLogic(logic, () => logic.actions.setColumnConfigSaving(true)).toMatchValues({
            columnConfigSaving: true,
        })
    })

    it('sets column config saving to false when user update succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.setColumnConfigSaving(true)
            userLogic.actions.updateUserSuccess(fakeUser)
        }).toMatchValues({
            columnConfigSaving: false,
        })
    })

    it('sets modal to hidden when user has selected columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.setModalVisible(true)
            logic.actions.setColumnConfig(['a'])
        }).toMatchValues({
            modalVisible: false,
        })
    })

    it('sets modal to hidden when user has saved columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.setModalVisible(true)
            logic.actions.saveSelectedColumns(['a'])
        })
            .delay(0)
            .toMatchValues({
                modalVisible: false,
            })
    })

    it('stores the columns on the user when they choose to save columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.setModalVisible(true)
            logic.actions.saveSelectedColumns(['a'])
        }).toDispatchActions([builtUserLogic.actionCreators.updateUser({ events_column_config: { active: ['a'] } })])
    })

    it('sets column config saving to false when user update fails', async () => {
        await expectLogic(logic, () => {
            logic.actions.setColumnConfigSaving(true)
            userLogic.actions.updateUserFailure('an error')
        }).toMatchValues({
            columnConfigSaving: false,
        })
    })

    it('sets table width to one more than column length to account for the button column', async () => {
        await expectLogic(logic, () => logic.actions.setColumnConfig(['a', 'b'])).toMatchValues({
            tableWidth: 3,
        })
    })
})
