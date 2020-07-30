// Auto-generated with kea-typegen. DO NOT EDIT!

export interface promptType {
    key: any
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
            payload: { title: any; placeholder: any; value: any; error: any; success: any; failure: any }
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
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['lib', 'logic', 'prompt']
    pathString: 'lib.logic.prompt'
    propTypes: any
    props: Record<string, any>
    reducer: (state: any, action: () => any, fullState: any) => {}
    reducerOptions: any
    reducers: {}
    selector: (state: any) => {}
    selectors: {}
    values: {}
    _isKea: true
}
