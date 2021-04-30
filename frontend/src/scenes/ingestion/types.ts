import {
    API,
    MOBILE,
    mobileFrameworks,
    BACKEND,
    WEB,
    webFrameworks,
    clientFrameworks,
} from 'scenes/ingestion/constants'

export type Framework =
    | keyof typeof webFrameworks
    | keyof typeof mobileFrameworks
    | typeof API
    | null
    | keyof typeof clientFrameworks
export type PlatformType = typeof WEB | typeof MOBILE | typeof BACKEND | null
