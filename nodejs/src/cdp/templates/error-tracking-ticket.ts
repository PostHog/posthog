const EXCEPTION_TYPE = 'event.properties.$exception_types[1]'
const EXCEPTION_MESSAGE = 'event.properties.$exception_values[1]'

const ticketCode = (value: string): string =>
    `concat('\`', replaceAll(replaceAll(replaceAll(${value}, '\`', '\\''), '\\n', ' '), '\\r', ' '), '\`')`

const ticketLine = (
    label: string,
    value: string,
    condition = `notEmpty(${value})`,
    formatted = ticketCode(value)
): string => `{${condition} ? concat('\\n- ${label}: ', ${formatted}) : ''}`

const ticketMessage = (message: string): string =>
    `{notEmpty(${message}) ? concat('\`\`\`\\n', replaceAll(${message}, '\`', '\\''), '\\n\`\`\`') : ''}\n`
const SESSION_REPLAY_URL = "concat(project.url, '/replay/', encodeURLComponent(event.properties.$session_id))"

// Keep in step with the tracker entries in frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts
// and with products/error_tracking/skills/authoring-error-tracking-alerts/references/block-templates.md.
export const ERROR_TRACKING_TICKET_TITLE = `{substring(replaceAll(notEmpty(${EXCEPTION_MESSAGE}) ? concat(${EXCEPTION_TYPE}, ': ', ${EXCEPTION_MESSAGE}) : ${EXCEPTION_TYPE}, '\\n', ' '), 1, 120)}`

// A Markdown list because GitLab joins consecutive plain lines into one paragraph. Values sit in code so
// that client-sent text cannot render links, images or @mentions in the tracker.
export const ERROR_TRACKING_TICKET_DESCRIPTION = [
    ticketMessage(EXCEPTION_MESSAGE),
    ticketLine('Browser', "trim(concat(event.properties.$browser, ' ', event.properties.$browser_version))"),
    ticketLine('OS', "trim(concat(event.properties.$os, ' ', event.properties.$os_version))"),
    ticketLine('Release', 'event.properties.$exception_release.version'),
    ticketLine(
        'Session replay',
        SESSION_REPLAY_URL,
        "notEmpty(event.properties.$session_id) and (empty(event.properties.$recording_status) or has(['active', 'sampled', 'buffering'], event.properties.$recording_status))",
        SESSION_REPLAY_URL
    ),
].join('')
