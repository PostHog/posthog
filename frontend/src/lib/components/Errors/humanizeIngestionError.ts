export interface HumanizedIngestionError {
    message: string
    docsLink?: string
}

const DOCS_LINK = 'https://posthog.com/docs/error-tracking/installation'

const SERDE_PREFIX = /^Invalid properties on event [0-9a-fA-F-]+, serde error: /
const EMPTY_EXCEPTION_LIST = /^Empty exception list on event [0-9a-fA-F-]+$/
const MISSING_FIELD = /missing field `([^`]+)`/
const NULL_FIELD = /invalid type: null, expected a ([a-z]+)/

const NO_EXCEPTION_DATA = "This event didn't include any exception data, so there's no stack trace to show."

/** Turns cymbal's raw Rust deserialization errors into something a customer can act on. */
export function humanizeIngestionError(error: string): HumanizedIngestionError {
    if (EMPTY_EXCEPTION_LIST.test(error)) {
        return { message: NO_EXCEPTION_DATA, docsLink: DOCS_LINK }
    }

    const detail = error.replace(SERDE_PREFIX, '')
    if (detail === error) {
        // Not a deserialization failure, so it already reads as a sentence
        return { message: error }
    }

    const missingField = detail.match(MISSING_FIELD)
    if (missingField) {
        if (missingField[1] === '$exception_list') {
            return { message: NO_EXCEPTION_DATA, docsLink: DOCS_LINK }
        }
        // Deliberately doesn't say which object was missing the field. The same
        // serde message covers the exception and its nested stacktrace, and
        // naming the wrong one sends people looking in the wrong place.
        return {
            message: `PostHog couldn't read this exception: your SDK left out a required "${missingField[1]}" field. Updating to the latest SDK version usually fixes this.`,
            docsLink: DOCS_LINK,
        }
    }

    const nullField = detail.match(NULL_FIELD)
    if (nullField) {
        return {
            message: `PostHog couldn't read this exception: your SDK sent an empty value where a ${nullField[1]} was expected. Updating to the latest SDK version usually fixes this.`,
            docsLink: DOCS_LINK,
        }
    }

    return {
        message: `PostHog couldn't read the exception data your SDK sent: ${detail}`,
        docsLink: DOCS_LINK,
    }
}
