import { actions, getPluginContext, listeners, LogicBuilder, reducers, selectors } from 'kea'
import { LoaderDefinitions } from 'kea-loaders'

export function lazyLoaders<L extends Logic = Logic>(
    input: LoaderDefinitions<L> | ((logic: L) => LoaderDefinitions<L>)
): LogicBuilder<L> {
    return (logic) => {
        const loaders = typeof input === 'function' ? input(logic) : input

        for (const [reducerKey, actionsInput] of Object.entries(loaders)) {
            let defaultValue = logic.defaults[reducerKey]

            let actionsObject = actionsInput
            if (Array.isArray(actionsObject)) {
                if (typeof defaultValue === 'undefined') {
                    defaultValue = actionsObject[0]
                }
                actionsObject = actionsObject[1] || {}
            }

            const { __default, ...loaderActions } = actionsObject
            if (typeof defaultValue === 'undefined' && typeof __default !== 'undefined') {
                defaultValue = typeof __default === 'function' ? __default() : __default
            }
            if (typeof defaultValue === 'undefined') {
                defaultValue = null
            }

            const newActions: Record<string, any> = {}
            Object.keys(loaderActions).forEach((actionKey) => {
                if (typeof logic.actions[`${actionKey}`] === 'undefined') {
                    newActions[`${actionKey}`] = (params: any) => params
                }
                if (typeof logic.actions[`${actionKey}Success`] === 'undefined') {
                    newActions[`${actionKey}Success`] = (value: any, payload: any) => ({ payload, [reducerKey]: value })
                }
                if (typeof logic.actions[`${actionKey}Failure`] === 'undefined') {
                    newActions[`${actionKey}Failure`] = (error: any, errorObject: any) => ({ error, errorObject })
                }
            })

            const newReducers: Record<string, any> = {}
            const reducerObject: Record<string, (state: any, payload: any) => any> = {}
            const reducerLoadingObject: Record<string, () => any> = {}
            let firstActionKey: string | undefined = undefined
            Object.keys(loaderActions).forEach((actionKey) => {
                if (!firstActionKey) {
                    firstActionKey = actionKey
                }
                reducerObject[`${actionKey}Success`] = (_, { [reducerKey]: value }) => value
                reducerLoadingObject[`${actionKey}`] = () => true
                reducerLoadingObject[`${actionKey}Success`] = () => false
                reducerLoadingObject[`${actionKey}Failure`] = () => false
            })
            if (typeof logic.reducers[reducerKey] === 'undefined') {
                newReducers[`${reducerKey}Source`] = [defaultValue, reducerObject]
            } else {
                newReducers[`${reducerKey}Source`] = reducerObject
            }
            if (typeof logic.reducers[`${reducerKey}Loading`] === 'undefined') {
                newReducers[`${reducerKey}Loading`] = [false, reducerLoadingObject]
            }

            // THIS PART IS NEW
            const newSelectors: Record<string, any> = {}
            newSelectors[reducerKey] = [
                (s) => [s[`${reducerKey}Source`]],
                (value) => {
                    if (firstActionKey && !logic.cache[`lazyLoaderCalled-${firstActionKey}`]) {
                        // eslint-disable-next-line no-console
                        console.log(
                            '[KEA-LAZY-LOADERES]',
                            `Calling actions.${firstActionKey}() because ${reducerKey} was accessed`
                        )
                        logic.cache[`lazyLoaderCalled-${firstActionKey}`] = true
                        window.setTimeout(() => logic.actions[firstActionKey]?.(), 0)
                    }
                    return value
                },
            ]
            // END NEW PART

            const newListeners: Record<string, ListenerFunction> = {}
            Object.entries(loaderActions).forEach(([actionKey, listener]) => {
                newListeners[actionKey] = (payload, breakpoint, action) => {
                    const { onStart, onSuccess, onFailure } = getPluginContext<KeaLoadersOptions>('loaders')
                    try {
                        onStart && onStart({ actionKey, reducerKey, logic })
                        // @ts-expect-error
                        const response = listener(payload, breakpoint, action)

                        if (response && response.then && typeof response.then === 'function') {
                            return response
                                .then((asyncResponse: any) => {
                                    onSuccess && onSuccess({ response: asyncResponse, actionKey, reducerKey, logic })
                                    logic.actions[`${actionKey}Success`](asyncResponse, payload)
                                })
                                .catch((error: Error) => {
                                    if (!isBreakpoint(error)) {
                                        onFailure && onFailure({ error, actionKey, reducerKey, logic, response })
                                        logic.actions[`${actionKey}Failure`](error.message, error)
                                    }
                                })
                        }
                        onSuccess && onSuccess({ response, actionKey, reducerKey, logic })
                        logic.actions[`${actionKey}Success`](response, payload)
                    } catch (error: any) {
                        if (!isBreakpoint(error)) {
                            onFailure && onFailure({ error, actionKey, reducerKey, logic })
                            logic.actions[`${actionKey}Failure`](error.message, error)
                        }
                    }
                }
            })

            // @ts-expect-error
            actions<L>(newActions)(logic)
            reducers<L>(newReducers)(logic)
            selectors<L>(newSelectors)(logic)
            listeners(newListeners)(logic)
        }
    }
}
