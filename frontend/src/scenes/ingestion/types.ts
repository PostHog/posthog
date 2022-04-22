import {
    API,
    MOBILE,
    mobileFrameworks,
    BACKEND,
    WEB,
    webFrameworks,
    clientFrameworks,
    APP,
    BOOKMARKLET,
} from 'scenes/ingestion/constants'

export type Framework =
    | keyof typeof webFrameworks
    | keyof typeof mobileFrameworks
    | typeof API
    | null
    | keyof typeof clientFrameworks

export type PlatformType = typeof WEB | typeof MOBILE | typeof BACKEND | typeof APP | typeof BOOKMARKLET | null
