// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface promptType extends Logic {
    actionCreators: {
        prompt: ({
            title,
            placeholder,
            value,
            error,
            success,
            failure,
        }: any) => {
            type: 'prompt (lib.logic.prompt)'
            payload: {
                title: any
                placeholder: any
                value: any
                error: any
                success: any
                failure: any
            }
        }
    }
    actionKeys: {
        'prompt (lib.logic.prompt)': 'prompt'
    }
    actionTypes: {
        prompt: 'prompt (lib.logic.prompt)'
    }
    actions: {
        prompt: ({ title, placeholder, value, error, success, failure }: any) => void
    }
    constants: {}
    defaults: {}
    events: {
        beforeUnmount: () => void
    }
    key: any
    listeners: {
        prompt: ((
            payload: {
                title: any
                placeholder: any
                value: any
                error: any
                success: any
                failure: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'prompt (lib.logic.prompt)'
                payload: {
                    title: any
                    placeholder: any
                    value: any
                    error: any
                    success: any
                    failure: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['lib', 'logic', 'prompt']
    pathString: 'lib.logic.prompt'
    props: Record<string, unknown>
    reducer: (state: any, action: () => any, fullState: any) => {}
    reducerOptions: {}
    reducers: {}
    selector: (state: any) => {}
    selectors: {}
    sharedListeners: {}
    values: {}
    _isKea: true
    _isKeaWithKey: true
}
