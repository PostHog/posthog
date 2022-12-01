import { API, MOBILE, mobileFrameworks, BACKEND, WEB, webFrameworks, THIRD_PARTY } from 'scenes/ingestion/v2/constants'

export type Framework = keyof typeof webFrameworks | keyof typeof mobileFrameworks | typeof API | null

export type PlatformType = typeof WEB | typeof MOBILE | typeof BACKEND | typeof THIRD_PARTY | null
