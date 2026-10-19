/**
 * Hog snippets shared across templates. Prepended into a template's `code`, so the functions
 * they define are callable from the rest of that template's Hog source.
 */

/**
 * Pulls the human-readable message out of a PostHog API error response, so a failing template
 * surfaces "Invalid API key" rather than a bare status code. Falls back to the whole body for
 * responses that don't use either of our standard error shapes.
 */
export const hogApiErrorMessageFn = `fun apiErrorMessage(response) {
  return response.body.error ?? response.body.detail ?? response.body
}`

const EXCEPTION_TYPE = 'event.properties.$exception_types[1]'
const EXCEPTION_MESSAGE = 'event.properties.$exception_values[1]'

const ticketLine = (label: string, value: string, condition = `notEmpty(${value})`): string =>
    `{${condition} ? concat('\\n- ${label}: ', ${value}) : ''}`

// Keep in step with the tracker entries in frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts.
export const ERROR_TRACKING_TICKET_TITLE = `{substring(notEmpty(${EXCEPTION_MESSAGE}) ? concat(${EXCEPTION_TYPE}, ': ', ${EXCEPTION_MESSAGE}) : ${EXCEPTION_TYPE}, 1, 120)}`

// A Markdown list because GitLab joins consecutive plain lines into one paragraph.
export const ERROR_TRACKING_TICKET_DESCRIPTION = [
    `{${EXCEPTION_MESSAGE}}\n`,
    ticketLine('URL', 'event.properties.$current_url'),
    ticketLine('Browser', "trim(concat(event.properties.$browser, ' ', event.properties.$browser_version))"),
    ticketLine('OS', "trim(concat(event.properties.$os, ' ', event.properties.$os_version))"),
    ticketLine('Release', 'event.properties.$exception_release.version'),
    ticketLine(
        'Session replay',
        "concat(project.url, '/replay/', encodeURLComponent(event.properties.$session_id))",
        "notEmpty(event.properties.$session_id) and (empty(event.properties.$recording_status) or has(['active', 'sampled', 'buffering'], event.properties.$recording_status))"
    ),
].join('')
