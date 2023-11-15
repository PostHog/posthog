import { API, BACKEND, MOBILE, mobileFrameworks, THIRD_PARTY, WEB, webFrameworks } from 'scenes/ingestion/constants'

export type Framework = keyof typeof webFrameworks | keyof typeof mobileFrameworks | typeof API | null

export type PlatformType = typeof WEB | typeof MOBILE | typeof BACKEND | typeof THIRD_PARTY | null
