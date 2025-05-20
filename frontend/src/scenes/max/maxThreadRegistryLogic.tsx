import { actions, BuiltLogic, connect, kea, listeners, path, reducers } from 'kea'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import posthog from 'posthog-js'

import { maxLogic } from './maxLogic'
import type { maxThreadLogicType } from './maxThreadLogicType'
import type { maxThreadRegistryLogicType } from './maxThreadRegistryLogicType'

export const maxThreadRegistryLogic = kea<maxThreadRegistryLogicType>([
    path(['scenes', 'max', 'maxThreadRegistryLogic']),
    connect(() => ({
        values: [maxLogic, ['conversationId']],
    })),
    permanentlyMount(),
    actions({
        registerThreadLogic: (logic: BuiltLogic<maxThreadLogicType>) => ({ logic }),
        cleanMountedThreadLogics: true,
        setMountedThreadLogics: (logics: Record<string, BuiltLogic<maxThreadLogicType>>) => ({ logics }),
    }),
    reducers({
        mountedThreadLogics: [
            {} as Record<string, BuiltLogic<maxThreadLogicType>>,
            {
                registerThreadLogic: (state, { logic }) => ({ ...state, [logic.pathString]: logic }),
                setMountedThreadLogics: (_, { logics }) => logics,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        cleanMountedThreadLogics: () => {
            // This action happens after the component lifecycle, so should be safe to unmount logics
            // as components are already unmounted.
            const logics = []
            for (const [path, logic] of Object.entries(values.mountedThreadLogics)) {
                try {
                    // If not mounted, just skip
                    if (!logic.isMounted()) {
                        continue
                    }

                    // If it's a current conversation or streaming, keep it.
                    if (logic.key === values.conversationId || logic.values.threadLoading) {
                        logics.push([path, logic])
                    } else {
                        // Otherwise, destroy
                        logic.unmount()
                    }
                } catch (e) {
                    posthog.captureException(e, {
                        tag: 'max',
                    })
                }
            }

            actions.setMountedThreadLogics(Object.fromEntries(logics))
        },
    })),
])
