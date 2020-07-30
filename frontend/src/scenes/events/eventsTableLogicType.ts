// Auto-generated with kea-typegen. DO NOT EDIT!

export interface eventsTableLogicType {
    key: any
    actionCreators: {
        setProperties: (
            properties: any
        ) => {
            type: 'set properties (frontend.src.scenes.events.eventsTableLogic)'
            payload: { properties: any }
        }
        fetchEvents: (
            nextParams?: any
        ) => {
            type: 'fetch events (frontend.src.scenes.events.eventsTableLogic)'
            payload: { nextParams: any }
        }
        fetchEventsSuccess: (
            events: any,
            hasNext?: any,
            isNext?: any
        ) => {
            type: 'fetch events success (frontend.src.scenes.events.eventsTableLogic)'
            payload: { events: any; hasNext: boolean; isNext: boolean }
        }
        fetchNextEvents: () => {
            type: 'fetch next events (frontend.src.scenes.events.eventsTableLogic)'
            payload: {
                value: boolean
            }
        }
        flipSort: () => {
            type: 'flip sort (frontend.src.scenes.events.eventsTableLogic)'
            payload: {
                value: boolean
            }
        }
        pollEvents: () => {
            type: 'poll events (frontend.src.scenes.events.eventsTableLogic)'
            payload: {
                value: boolean
            }
        }
        pollEventsSuccess: (
            events: any
        ) => {
            type: 'poll events success (frontend.src.scenes.events.eventsTableLogic)'
            payload: { events: any }
        }
        prependNewEvents: (
            events: any
        ) => {
            type: 'prepend new events (frontend.src.scenes.events.eventsTableLogic)'
            payload: { events: any }
        }
        setSelectedEvent: (
            selectedEvent: any
        ) => {
            type: 'set selected event (frontend.src.scenes.events.eventsTableLogic)'
            payload: { selectedEvent: any }
        }
        setPollTimeout: (
            pollTimeout: any
        ) => {
            type: 'set poll timeout (frontend.src.scenes.events.eventsTableLogic)'
            payload: { pollTimeout: any }
        }
        setDelayedLoading: () => {
            type: 'set delayed loading (frontend.src.scenes.events.eventsTableLogic)'
            payload: {
                value: boolean
            }
        }
        setEventFilter: (
            event: any
        ) => {
            type: 'set event filter (frontend.src.scenes.events.eventsTableLogic)'
            payload: { event: any }
        }
    }
    actionKeys: {
        'set properties (frontend.src.scenes.events.eventsTableLogic)': 'setProperties'
        'fetch events (frontend.src.scenes.events.eventsTableLogic)': 'fetchEvents'
        'fetch events success (frontend.src.scenes.events.eventsTableLogic)': 'fetchEventsSuccess'
        'fetch next events (frontend.src.scenes.events.eventsTableLogic)': 'fetchNextEvents'
        'flip sort (frontend.src.scenes.events.eventsTableLogic)': 'flipSort'
        'poll events (frontend.src.scenes.events.eventsTableLogic)': 'pollEvents'
        'poll events success (frontend.src.scenes.events.eventsTableLogic)': 'pollEventsSuccess'
        'prepend new events (frontend.src.scenes.events.eventsTableLogic)': 'prependNewEvents'
        'set selected event (frontend.src.scenes.events.eventsTableLogic)': 'setSelectedEvent'
        'set poll timeout (frontend.src.scenes.events.eventsTableLogic)': 'setPollTimeout'
        'set delayed loading (frontend.src.scenes.events.eventsTableLogic)': 'setDelayedLoading'
        'set event filter (frontend.src.scenes.events.eventsTableLogic)': 'setEventFilter'
    }
    actionTypes: {
        setProperties: 'set properties (frontend.src.scenes.events.eventsTableLogic)'
        fetchEvents: 'fetch events (frontend.src.scenes.events.eventsTableLogic)'
        fetchEventsSuccess: 'fetch events success (frontend.src.scenes.events.eventsTableLogic)'
        fetchNextEvents: 'fetch next events (frontend.src.scenes.events.eventsTableLogic)'
        flipSort: 'flip sort (frontend.src.scenes.events.eventsTableLogic)'
        pollEvents: 'poll events (frontend.src.scenes.events.eventsTableLogic)'
        pollEventsSuccess: 'poll events success (frontend.src.scenes.events.eventsTableLogic)'
        prependNewEvents: 'prepend new events (frontend.src.scenes.events.eventsTableLogic)'
        setSelectedEvent: 'set selected event (frontend.src.scenes.events.eventsTableLogic)'
        setPollTimeout: 'set poll timeout (frontend.src.scenes.events.eventsTableLogic)'
        setDelayedLoading: 'set delayed loading (frontend.src.scenes.events.eventsTableLogic)'
        setEventFilter: 'set event filter (frontend.src.scenes.events.eventsTableLogic)'
    }
    actions: {
        setProperties: (properties: any) => void
        fetchEvents: (nextParams?: any) => void
        fetchEventsSuccess: (events: any, hasNext?: any, isNext?: any) => void
        fetchNextEvents: () => void
        flipSort: () => void
        pollEvents: () => void
        pollEventsSuccess: (events: any) => void
        prependNewEvents: (events: any) => void
        setSelectedEvent: (selectedEvent: any) => void
        setPollTimeout: (pollTimeout: any) => void
        setDelayedLoading: () => void
        setEventFilter: (event: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'events', 'eventsTableLogic']
    pathString: 'frontend.src.scenes.events.eventsTableLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        initialPathname: (state: any) => any
        properties: never[]
        eventFilter: boolean
        isLoading: boolean
        isLoadingNext: boolean
        events: never[]
        hasNext: boolean
        orderBy: string
        selectedEvent: null
        newEvents: never[]
        highlightEvents: {}
        pollTimeout: null
    }
    reducerOptions: any
    reducers: {
        initialPathname: (state: (state: any) => any, action: any, fullState: any) => (state: any) => any
        properties: (state: never[], action: any, fullState: any) => never[]
        eventFilter: (state: boolean, action: any, fullState: any) => boolean
        isLoading: (state: boolean, action: any, fullState: any) => boolean
        isLoadingNext: (state: boolean, action: any, fullState: any) => boolean
        events: (state: never[], action: any, fullState: any) => never[]
        hasNext: (state: boolean, action: any, fullState: any) => boolean
        orderBy: (state: string, action: any, fullState: any) => string
        selectedEvent: (state: null, action: any, fullState: any) => null
        newEvents: (state: never[], action: any, fullState: any) => never[]
        highlightEvents: (state: {}, action: any, fullState: any) => {}
        pollTimeout: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        initialPathname: (state: any) => any
        properties: never[]
        eventFilter: boolean
        isLoading: boolean
        isLoadingNext: boolean
        events: never[]
        hasNext: boolean
        orderBy: string
        selectedEvent: null
        newEvents: never[]
        highlightEvents: {}
        pollTimeout: null
    }
    selectors: {
        initialPathname: (state: any, props: any) => (state: any) => any
        properties: (state: any, props: any) => never[]
        eventFilter: (state: any, props: any) => boolean
        isLoading: (state: any, props: any) => boolean
        isLoadingNext: (state: any, props: any) => boolean
        events: (state: any, props: any) => never[]
        hasNext: (state: any, props: any) => boolean
        orderBy: (state: any, props: any) => string
        selectedEvent: (state: any, props: any) => null
        newEvents: (state: any, props: any) => never[]
        highlightEvents: (state: any, props: any) => {}
        pollTimeout: (state: any, props: any) => null
        propertiesForUrl: (state: any, props: any) => '' | { properties: any }
        eventsFormatted: (state: any, props: any) => any[]
    }
    values: {
        initialPathname: (state: any) => any
        properties: never[]
        eventFilter: boolean
        isLoading: boolean
        isLoadingNext: boolean
        events: never[]
        hasNext: boolean
        orderBy: string
        selectedEvent: null
        newEvents: never[]
        highlightEvents: {}
        pollTimeout: null
        propertiesForUrl: '' | { properties: any }
        eventsFormatted: any[]
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        propertiesForUrl: (arg1: any) => '' | { properties: any }
        eventsFormatted: (arg1: any, arg2: any) => any[]
    }
}
