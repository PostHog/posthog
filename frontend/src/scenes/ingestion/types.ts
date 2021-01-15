import { API, MOBILE, mobileFrameworks, SERVER, WEB, webFrameworks } from 'scenes/ingestion/constants'

export type Framework = keyof typeof webFrameworks | keyof typeof mobileFrameworks | typeof API | null
export type PlatformType = typeof WEB | typeof MOBILE | typeof SERVER | null
