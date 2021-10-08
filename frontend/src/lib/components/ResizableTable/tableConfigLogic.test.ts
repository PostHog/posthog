import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { UserType } from '~/types'
import { userLogic } from 'scenes/userLogic'

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
        logic: userLogic,
        props: {},
        onLogic: (l) => (builtUserLogic = l),
    })

    initKeaTestLogic({
        logic: tableConfigLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    it('starts with expected defaults', async () => {
        await expectLogic(logic).toMount(builtUserLogic).toMatchValues({
            columnConfigSaving: false,
            modalVisible: false,
            columnConfig: 'DEFAULT',
            tableWidth: 7,
        })
    })

    it('can set column config saving', async () => {
        await expectLogic(logic, () => logic.actions.setColumnConfigSaving(true)).toMatchValues({
            columnConfigSaving: true,
        })
    })

    it('can set modal visible', async () => {
        await expectLogic(logic, () => logic.actions.setModalVisible(true)).toMatchValues({
            modalVisible: true,
        })
    })

    it('can set column config', async () => {
        const columnConfig = ['a', 'b']
        await expectLogic(logic, () => logic.actions.setColumnConfig(columnConfig))
            .toDispatchActions([
                logic.actionCreators.setColumnConfigSaving(true),
                userLogic.actionCreators.updateUser({ events_column_config: { active: columnConfig } }),
            ])
            .toMatchValues({
                columnConfig,
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

    it('sets modal to hidden when user update succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.setModalVisible(true)
            userLogic.actions.updateUserSuccess(fakeUser)
        }).toMatchValues({
            modalVisible: false,
        })
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
