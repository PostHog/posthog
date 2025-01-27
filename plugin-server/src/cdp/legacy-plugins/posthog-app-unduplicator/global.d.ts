/* eslint-disable no-var */

interface ApiMethodOptions {
    data?: Record<string, any> // any data to send with the request, GET and DELETE will set these as URL params
    host?: string // posthog host, defaults to https://app.posthog.com
    projectApiKey?: string // specifies the project to interact with
    personalApiKey?: string // authenticates the user
}

interface APIInterface {
    get: (path: string, options?: ApiMethodOptions) => Promise<Record<string, any>>
}

declare namespace posthog {
    var api: APIInterface
}
