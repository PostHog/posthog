import { setPluginContext, getPluginContext } from 'kea'
import type { BuiltLogic, CreateStoreOptions, KeaPlugin, LogicInput } from 'kea'

type Subscription = {
    selector: (state: any, props: any) => any
    subscription: (value: any, lastValue: any) => void
    lastValue: any
    logic: BuiltLogic
}
type SubscribersPluginContext = {
    byPath: Record<string, Subscription[]>
}

export const subscriptionsPlugin: KeaPlugin = {
    name: 'subscriptions',

    defaults: () => ({
        subscriptions: undefined,
    }),

    buildOrder: {
        subscriptions: { after: 'listeners' },
    },

    buildSteps: {
        subscriptions(logic: BuiltLogic, input: LogicInput): void {
            if (!input.subscriptions) {
                return
            }

            const newSubscribers = (
                typeof input.subscriptions === 'function' ? input.subscriptions(logic) : input.subscriptions
            ) as Record<string, Subscription['subscription']>

            ;(logic as any).subscriptions = [
                ...((logic as any).subscriptions || []),
                ...Object.keys(newSubscribers).map(
                    (selectorKey) =>
                        ({
                            selector: logic.selectors[selectorKey],
                            subscription: newSubscribers[selectorKey],
                            lastValue: undefined,
                            logic: logic,
                        } as Subscription)
                ),
            ]
        },
    },

    events: {
        afterPlugin(): void {
            setPluginContext('subscriptions', {
                byPath: {},
            } as SubscribersPluginContext)
        },

        beforeReduxStore(options: CreateStoreOptions): void {
            options.middleware.push((store) => (next) => (action) => {
                const response = next(action)

                const { byPath } = getPluginContext('subscriptions') as SubscribersPluginContext

                for (const subscriberArray of Object.values(byPath)) {
                    for (const sub of subscriberArray) {
                        try {
                            const newValue = sub.selector(store.getState(), sub.logic.props)
                            if (sub.lastValue !== newValue) {
                                const lastValue = sub.lastValue
                                sub.lastValue = newValue
                                sub.subscription(newValue, lastValue)
                            }
                        } catch (e) {
                            // ignore noise if the new or old value is not in redux
                        }
                    }
                }
                return response
            })
        },

        afterMount(logic: any): void {
            if (!logic.subscriptions) {
                return
            }
            addSubscriptionsByPathString(logic.pathString, logic.subscriptions)
        },

        beforeUnmount(logic: any): void {
            if (!logic.subscriptions) {
                return
            }
            removeSubscriptionsByPathString(logic.pathString)
        },

        beforeCloseContext(): void {
            setPluginContext('subscriptions', { byAction: {}, byPath: {} } as SubscribersPluginContext)
        },
    },
}

function addSubscriptionsByPathString(pathString: string, subscriptions: Subscription[]): void {
    const { byPath } = getPluginContext('subscriptions') as SubscribersPluginContext
    byPath[pathString] = subscriptions
}

function removeSubscriptionsByPathString(pathString: string): void {
    const { byPath } = getPluginContext('subscriptions') as SubscribersPluginContext
    delete byPath[pathString]
}
