import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-semver-flattener',
    name: 'SemVer Flattener',
    description:
        'Splits semantic version strings in the chosen properties into separate major, minor, patch, pre-release and build properties.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(event.properties)) {
    return event
}

let returnEvent := event
let targets := splitByString(',', inputs.properties)

for (let target in targets) {
    let name := trim(target)
    if (not empty(name)) {
        let candidate := event.properties[name]
        if (not empty(candidate) and typeof(candidate) == 'string') {
            // Build metadata is everything after the first '+'
            let head := candidate
            let build := null
            let plusPos := position(candidate, '+')
            if (plusPos > 0) {
                head := substring(candidate, 1, plusPos - 1)
                build := substring(candidate, plusPos + 1, length(candidate) - plusPos)
            }

            // Pre-release is everything after the first '-'
            let core := head
            let preRelease := null
            let dashPos := position(head, '-')
            if (dashPos > 0) {
                core := substring(head, 1, dashPos - 1)
                preRelease := substring(head, dashPos + 1, length(head) - dashPos)
            }

            let parts := splitByString('.', core)
            returnEvent.properties[concat(name, '__major')] := toInt(parts[1])
            returnEvent.properties[concat(name, '__minor')] := length(parts) > 1 ? toInt(parts[2]) : null
            if (length(parts) > 2) {
                returnEvent.properties[concat(name, '__patch')] := toInt(parts[3])
            }
            if (not empty(preRelease)) {
                returnEvent.properties[concat(name, '__preRelease')] := preRelease
            }
            if (not empty(build)) {
                returnEvent.properties[concat(name, '__build')] := build
            }
        }
    }
}

return returnEvent
    `,
    inputs_schema: [
        {
            key: 'properties',
            type: 'string',
            label: 'Properties to flatten',
            description:
                'Comma-separated list of properties holding semantic version strings (e.g. app_version, sdk_version).',
            default: '',
            required: true,
        },
    ],
}
