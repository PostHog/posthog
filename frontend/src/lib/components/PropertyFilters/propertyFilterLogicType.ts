// Auto-generated with kea-typegen. DO NOT EDIT!

export interface propertyFilterLogicType {
    key: any
    actionCreators: {
        loadEventProperties: () => {
            type: 'load event properties (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                value: boolean
            }
        }
        setProperties: (
            properties: any
        ) => {
            type: 'set properties (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { properties: any }
        }
        update: (
            filters: any
        ) => {
            type: 'update (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { filters: any }
        }
        setFilter: (
            index: any,
            key: any,
            value: any,
            operator: any,
            type: any
        ) => {
            type: 'set filter (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { index: any; key: any; value: any; operator: any; type: any }
        }
        setFilters: (
            filters: any
        ) => {
            type: 'set filters (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { filters: any }
        }
        newFilter: () => {
            type: 'new filter (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                value: boolean
            }
        }
        remove: (
            index: any
        ) => {
            type: 'remove (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { index: any }
        }
        loadPersonProperties: () => {
            type: 'load person properties (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: any
        }
        loadPersonPropertiesSuccess: (
            personProperties: any
        ) => {
            type: 'load person properties success (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                personProperties: any
            }
        }
        loadPersonPropertiesFailure: (
            error: string
        ) => {
            type: 'load person properties failure (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load event properties (lib.components.PropertyFilters.propertyFilterLogic)': 'loadEventProperties'
        'set properties (lib.components.PropertyFilters.propertyFilterLogic)': 'setProperties'
        'update (lib.components.PropertyFilters.propertyFilterLogic)': 'update'
        'set filter (lib.components.PropertyFilters.propertyFilterLogic)': 'setFilter'
        'set filters (lib.components.PropertyFilters.propertyFilterLogic)': 'setFilters'
        'new filter (lib.components.PropertyFilters.propertyFilterLogic)': 'newFilter'
        'remove (lib.components.PropertyFilters.propertyFilterLogic)': 'remove'
        'load person properties (lib.components.PropertyFilters.propertyFilterLogic)': 'loadPersonProperties'
        'load person properties success (lib.components.PropertyFilters.propertyFilterLogic)': 'loadPersonPropertiesSuccess'
        'load person properties failure (lib.components.PropertyFilters.propertyFilterLogic)': 'loadPersonPropertiesFailure'
    }
    actionTypes: {
        loadEventProperties: 'load event properties (lib.components.PropertyFilters.propertyFilterLogic)'
        setProperties: 'set properties (lib.components.PropertyFilters.propertyFilterLogic)'
        update: 'update (lib.components.PropertyFilters.propertyFilterLogic)'
        setFilter: 'set filter (lib.components.PropertyFilters.propertyFilterLogic)'
        setFilters: 'set filters (lib.components.PropertyFilters.propertyFilterLogic)'
        newFilter: 'new filter (lib.components.PropertyFilters.propertyFilterLogic)'
        remove: 'remove (lib.components.PropertyFilters.propertyFilterLogic)'
        loadPersonProperties: 'load person properties (lib.components.PropertyFilters.propertyFilterLogic)'
        loadPersonPropertiesSuccess: 'load person properties success (lib.components.PropertyFilters.propertyFilterLogic)'
        loadPersonPropertiesFailure: 'load person properties failure (lib.components.PropertyFilters.propertyFilterLogic)'
    }
    actions: {
        loadEventProperties: () => {
            type: 'load event properties (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                value: boolean
            }
        }
        setProperties: (
            properties: any
        ) => {
            type: 'set properties (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { properties: any }
        }
        update: (
            filters: any
        ) => {
            type: 'update (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { filters: any }
        }
        setFilter: (
            index: any,
            key: any,
            value: any,
            operator: any,
            type: any
        ) => {
            type: 'set filter (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { index: any; key: any; value: any; operator: any; type: any }
        }
        setFilters: (
            filters: any
        ) => {
            type: 'set filters (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { filters: any }
        }
        newFilter: () => {
            type: 'new filter (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                value: boolean
            }
        }
        remove: (
            index: any
        ) => {
            type: 'remove (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: { index: any }
        }
        loadPersonProperties: () => {
            type: 'load person properties (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: any
        }
        loadPersonPropertiesSuccess: (
            personProperties: any
        ) => {
            type: 'load person properties success (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                personProperties: any
            }
        }
        loadPersonPropertiesFailure: (
            error: string
        ) => {
            type: 'load person properties failure (lib.components.PropertyFilters.propertyFilterLogic)'
            payload: {
                error: string
            }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['lib', 'components', 'PropertyFilters', 'propertyFilterLogic']
    pathString: 'lib.components.PropertyFilters.propertyFilterLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        personProperties: any
        personPropertiesLoading: boolean
        eventProperties: undefined[]
        filters: any
    }
    reducerOptions: any
    reducers: {
        personProperties: (state: any, action: any, fullState: any) => any
        personPropertiesLoading: (state: boolean, action: any, fullState: any) => boolean
        eventProperties: (state: undefined[], action: any, fullState: any) => undefined[]
        filters: (state: any, action: any, fullState: any) => any
    }
    selector: (
        state: any
    ) => {
        personProperties: any
        personPropertiesLoading: boolean
        eventProperties: undefined[]
        filters: any
    }
    selectors: {
        personProperties: (state: any, props: any) => any
        personPropertiesLoading: (state: any, props: any) => boolean
        eventProperties: (state: any, props: any) => undefined[]
        filters: (state: any, props: any) => any
    }
    values: {
        personProperties: any
        personPropertiesLoading: boolean
        eventProperties: undefined[]
        filters: any
    }
    _isKea: true
}
