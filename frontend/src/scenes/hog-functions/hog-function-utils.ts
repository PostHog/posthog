import { HogFunctionTypeType } from '~/types'

export function humanizeHogFunctionType(type: HogFunctionTypeType): string {
    return type.replaceAll('_', ' ')
}
