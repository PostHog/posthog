import { AnnotationType } from '~/types'

export function getNextKey(arr: AnnotationType[]): number {
    if (arr.length === 0) {
        return -1
    }
    const result = arr.reduce((prev, curr) => (parseInt(prev.id) < parseInt(curr.id) ? prev : curr))
    if (parseInt(result.id) >= 0) {
        return -1
    } else {
        return parseInt(result.id) - 1
    }
}
