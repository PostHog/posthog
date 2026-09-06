import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-taxonomy',
    name: 'Taxonomy',
    description: 'Standardizes event names into one naming convention, such as camelCase or snake_case.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// PostHog's own events (names starting with $) and survey events keep their names.
if (empty(event.event) or startsWith(event.event, '$')) {
    return event
}
if (event.event == 'survey shown' or event.event == 'survey sent' or event.event == 'survey dismissed') {
    return event
}

fun isUpper(ch) {
    return upper(ch) == ch and lower(ch) != ch
}

fun isLower(ch) {
    return lower(ch) == ch and upper(ch) != ch
}

fun capitalize(word) {
    if (empty(word)) {
        return word
    }
    return concat(upper(substring(word, 1, 1)), substring(word, 2, length(word) - 1))
}

// Split a name into lowercased words on separators and on case boundaries,
// so 'userSignedUp', 'user_signed_up' and 'User Signed Up' all become ['user', 'signed', 'up'].
// Keep the last character in its own variable. Reading it back out of the word instead would
// pair length() with substring(), and those two count differently on one of the supported
// virtual machines, which drops the boundary after a word that holds a non-ASCII character.
fun tokenize(name) {
    let words := []
    let current := ''
    let previous := ''
    let i := 1
    while (i <= length(name)) {
        let ch := substring(name, i, 1)
        if (ch == '_' or ch == '-' or ch == ' ' or ch == '.') {
            if (not empty(current)) {
                words := arrayPushBack(words, lower(current))
                current := ''
            }
            previous := ''
        } else {
            // 'userSigned' breaks at the capital. 'APIResponse' breaks at the last capital of a
            // run, so the character after this one decides.
            let following := substring(name, i + 1, 1)
            if (
                isUpper(ch)
                and not empty(current)
                and (isLower(previous) or (isUpper(previous) and isLower(following)))
            ) {
                words := arrayPushBack(words, lower(current))
                current := ''
            }
            current := concat(current, ch)
            previous := ch
        }
        i := i + 1
    }
    if (not empty(current)) {
        words := arrayPushBack(words, lower(current))
    }
    return words
}

let words := tokenize(event.event)
if (empty(words)) {
    return event
}

let convention := inputs.namingConvention
let result := ''

if (convention == 'snake_case') {
    result := arrayStringConcat(words, '_')
} else if (convention == 'kebab-case') {
    result := arrayStringConcat(words, '-')
} else if (convention == 'spaces') {
    result := arrayStringConcat(words, ' ')
} else if (convention == 'camelCase' or convention == 'PascalCase') {
    let i := 1
    while (i <= length(words)) {
        if (i == 1 and convention == 'camelCase') {
            result := concat(result, words[i])
        } else {
            result := concat(result, capitalize(words[i]))
        }
        i := i + 1
    }
} else {
    // A convention outside the list keeps the name, because a renamed event cannot be undone.
    return event
}

let returnEvent := event
returnEvent.event := result
return returnEvent
    `,
    inputs_schema: [
        {
            key: 'namingConvention',
            type: 'choice',
            label: 'Naming convention',
            description: 'The convention every event name is converted to.',
            default: 'camelCase',
            required: true,
            choices: [
                { label: 'camelCase', value: 'camelCase' },
                { label: 'PascalCase', value: 'PascalCase' },
                { label: 'snake_case', value: 'snake_case' },
                { label: 'kebab-case', value: 'kebab-case' },
                { label: 'Spaces', value: 'spaces' },
            ],
        },
    ],
}
