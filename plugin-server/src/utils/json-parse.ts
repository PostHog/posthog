import { parse as simdjson_parse } from 'simdjson'

import { defaultConfig } from '../config/config'

export function parseJSON(json: string) {
    if (defaultConfig.USE_SIMD_JSON_PARSE) {
        return simdjson_parse(json)
    }
    // eslint-disable-next-line no-restricted-syntax
    return JSON.parse(json)
}
