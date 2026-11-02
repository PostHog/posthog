import type { AppContext } from '~/types'

// The keys `add_user_app_context` in posthog/utils.py fills. A deferred page gets them after the boot modules load.
const USER_APP_CONTEXT_KEYS = [
    'current_user',
    'current_team',
    'current_project',
    'effective_resource_access_control',
    'resource_access_control',
    'frontend_apps',
    'default_event_name',
    'has_pageview',
    'has_screen',
    'has_person_email',
    'homepage',
]

describe('app boot modules', () => {
    afterEach(() => {
        delete window.POSTHOG_APP_CONTEXT
    })

    it('do not read the user data when they load', async () => {
        const userKeysRead = new Set<string>()
        window.POSTHOG_APP_CONTEXT = new Proxy({ anonymous: false, deferred: true } as unknown as AppContext, {
            get(target, key, receiver) {
                if (typeof key === 'string' && USER_APP_CONTEXT_KEYS.includes(key)) {
                    userKeysRead.add(key)
                }
                return Reflect.get(target, key, receiver)
            },
        })

        await jest.isolateModulesAsync(async () => {
            await import('scenes/App')
            await import('scenes/bootApp')
        })

        expect([...userKeysRead]).toEqual([])
    })
})
