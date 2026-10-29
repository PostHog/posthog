/**
 * @jest-environment-options {"url": "https://app.example.com/project/1"}
 */
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { createMemoryHistory } from 'history'

import type { userLogic as UserLogic } from 'scenes/userLogic'

import { AppContext, PreflightStatus, Realm, UserType } from '~/types'

// The real SDK decides when /flags is requested, so these tests count the requests it sends.
jest.unmock('posthog-js')
// The toolbar starts a second posthog-js instance with its own flags requests, which are out of scope here.
jest.mock('~/toolbar/shared/toolbarPosthogJS', () => ({
    toolbarPosthogJS: {},
    captureToolbarException: jest.fn(),
    useToolbarFeatureFlag: () => false,
}))

interface FlagsRequestBody {
    distinct_id: string
    $anon_distinct_id?: string
    groups: Record<string, string>
    group_properties?: Record<string, Record<string, unknown>>
    person_properties: Record<string, unknown>
}

const PROJECT_TOKEN = 'phc_example'
const SITE_URL = 'https://posthog.example.com'

const userInProject = (projectUuid: string): UserType => ({
    ...MOCK_DEFAULT_USER,
    realm: Realm.Cloud,
    team: { ...MOCK_DEFAULT_TEAM, uuid: projectUuid, name: `Project ${projectUuid}` },
    organization: { ...MOCK_DEFAULT_ORGANIZATION, customer_id: 'cus_example' },
})
const USER = userInProject('project-a')

interface Page {
    userLogic: typeof UserLogic
    flagsRequests: FlagsRequestBody[]
    groupIdentifyTypes: string[]
}

const LOGGED_OUT_FLAGS_REQUEST = expect.objectContaining({ groups: {} })

function loggedInFlagsRequest(user: UserType, anonymousId: string | undefined): FlagsRequestBody {
    return expect.objectContaining({
        distinct_id: user.distinct_id,
        ...(anonymousId ? { $anon_distinct_id: anonymousId } : {}),
        groups: {
            project: user.team!.uuid,
            organization: user.organization!.id,
            customer: user.organization!.customer_id,
            instance: SITE_URL,
        },
        person_properties: expect.objectContaining({ email: user.email, realm: user.realm }),
        group_properties: expect.objectContaining({
            instance: { site_url: SITE_URL },
            project: expect.objectContaining({ uuid: user.team!.uuid, name: user.team!.name }),
            organization: expect.objectContaining({ id: user.organization!.id, name: user.organization!.name }),
        }),
    })
}

function decodeFlagsRequest(body: ArrayBuffer): FlagsRequestBody {
    const data = new URLSearchParams(Buffer.from(body).toString()).get('data') ?? ''
    return JSON.parse(Buffer.from(data, 'base64').toString())
}

describe('loadPostHogJS feature flag requests', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        localStorage.clear()
        sessionStorage.clear()
        for (const cookie of document.cookie.split(';')) {
            const name = cookie.split('=')[0].trim()
            for (const domain of ['', '; domain=.example.com']) {
                document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${domain}`
            }
        }
        window.JS_POSTHOG_API_KEY = PROJECT_TOKEN
        window.JS_POSTHOG_HOST = 'https://us.example.com'
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /** Boots a fresh copy of posthog-js and the app logics that identify the user, like a full page load. */
    async function loadPage(user: UserType | null): Promise<Page> {
        jest.resetModules()
        // posthog-js keeps the fetch it finds at import, so the instance of an earlier page, which acts
        // like another open tab, records its requests elsewhere.
        const flagsRequests: FlagsRequestBody[] = []
        global.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
            if (String(url).includes('/flags/')) {
                flagsRequests.push(decodeFlagsRequest(init?.body as ArrayBuffer))
                return new Response(JSON.stringify({ flags: {} }), { status: 200 })
            }
            return new Response('{}', { status: 200 })
        }) as typeof fetch
        window.POSTHOG_APP_CONTEXT = {
            current_user: user,
            // The server leaves site_url out of the preflight for a logged-out visitor.
            preflight: (user ? { site_url: SITE_URL } : {}) as PreflightStatus,
        } as AppContext
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = user ? { featureFlags: { 'bootstrapped-flag': true } } : {}

        const posthog = (await import('posthog-js')).default
        const groupIdentifyTypes: string[] = []
        posthog.on('eventCaptured', ({ event, properties }) => {
            if (event === '$groupidentify') {
                groupIdentifyTypes.push(properties.$group_type)
            }
        })
        const { loadPostHogJS } = await import('./loadPostHogJS')
        const { initKea } = await import('./initKea')
        const { userLogic } = await import('scenes/userLogic')
        const { preflightLogic } = await import('lib/logic/preflightLogic')

        loadPostHogJS()
        const history = createMemoryHistory()
        initKea({ routerLocation: history.location, routerHistory: history })
        userLogic.mount()
        preflightLogic.mount()

        // posthog-js loads its remote config with a script tag, which jsdom never runs, so deliver it by hand.
        ;(window as any)._POSTHOG_REMOTE_CONFIG = { [PROJECT_TOKEN]: { config: {} } }
        document.querySelector<HTMLScriptElement>('script[src*="/config.js"]')?.onload?.(new Event('load'))

        await jest.advanceTimersByTimeAsync(1000)
        return { userLogic, flagsRequests, groupIdentifyTypes }
    }

    it.each<{
        case: string
        previousPage: UserType | null | undefined
        user: UserType | null
        groupIdentifyTypes: string[]
    }>([
        { case: 'a logged-out page', previousPage: undefined, user: null, groupIdentifyTypes: [] },
        {
            case: 'the first page after login',
            previousPage: null,
            user: USER,
            groupIdentifyTypes: ['project', 'organization', 'customer', 'instance'],
        },
        {
            case: 'a reload while logged in',
            previousPage: USER,
            user: USER,
            groupIdentifyTypes: ['project', 'organization', 'instance'],
        },
        {
            case: 'the page after a project switch',
            previousPage: userInProject('project-b'),
            user: USER,
            groupIdentifyTypes: ['project', 'organization', 'instance'],
        },
    ])('sends one flags request with every input on $case', async ({ previousPage, user, groupIdentifyTypes }) => {
        const previous = previousPage === undefined ? undefined : await loadPage(previousPage)
        // A login keeps the flag values the anonymous visitor had, for flags with experience continuity.
        const anonymousId = previousPage === null ? previous?.flagsRequests[0].distinct_id : undefined

        const page = await loadPage(user)

        expect(page.groupIdentifyTypes).toEqual(groupIdentifyTypes)
        expect(page.flagsRequests).toEqual([user ? loggedInFlagsRequest(user, anonymousId) : LOGGED_OUT_FLAGS_REQUEST])
    })

    it.each<{ case: string; loadedUser: UserType; requestedProjects: string[] }>([
        { case: 'the same user loads again', loadedUser: USER, requestedProjects: [] },
        {
            case: 'the user moves to another project',
            loadedUser: userInProject('project-b'),
            requestedProjects: ['project-b'],
        },
    ])(
        'loads flags only for a changed user when $case without a page load',
        async ({ loadedUser, requestedProjects }) => {
            const { userLogic, flagsRequests } = await loadPage(USER)
            flagsRequests.length = 0

            userLogic.actions.loadUserSuccess(loadedUser)
            await jest.advanceTimersByTimeAsync(1000)

            expect(flagsRequests.map((request) => request.groups.project)).toEqual(requestedProjects)
        }
    )
})
