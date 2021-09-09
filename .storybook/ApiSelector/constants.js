export const ADDON_ID = 'api-selector-v1'
export const GLOBAL_KEY = 'connection'
export const LOCALSTORAGE_KEY = 'api-storage'
export const LOCALSTORAGE_HISTORY_KEY = 'api-storage-history'
export const defaultConnection = { apiHost: '', apiKey: '' }

export const history = [
    { apiHost: '', apiKey: '' },
    { apiHost: 'http://localhost:8000', apiKey: '' },
    { apiHost: 'https://app.posthog.com', apiKey: '' },
]
