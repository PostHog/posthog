/**
 * Change Type Of Passed Value
 * @param {Type} type The type to be casted to
 * @param {Number/String} value the value to be changed
 **/
export function changeType(type, value) {
    switch (type) {
        case 'text':
            return String(value)
        case 'number':
            return Number(value)
        case 'boolean':
            return value == 'true' ? true : false
        case 'string':
            return String(value)
        default:
            throw 'Unsupported type'
    }
}
