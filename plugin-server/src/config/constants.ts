import { logLevel } from 'kafkajs'

export const ONE_MINUTE = 60 * 1000
export const ONE_HOUR = 60 * 60 * 1000
export const KAFKAJS_LOG_LEVEL_MAPPING = {
    NOTHING: logLevel.NOTHING,
    DEBUG: logLevel.INFO,
    INFO: logLevel.INFO,
    WARN: logLevel.WARN,
    ERROR: logLevel.ERROR,
}
export const ACCESS_TOKEN_PLACEHOLDER = '$$_access_token_placeholder_'
