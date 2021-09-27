import React, { useEffect } from 'react'
import { GLOBAL_KEY } from './constants'

export const withApi = (Story, context) => {
    const connection = context.globals[GLOBAL_KEY]
    const { apiKey, apiHost } = connection || {}

    useEffect(() => {
        const oldFetch = window.fetch
        window.fetch = (url, ...args) => {
            console.log('Intercepted Fetch', args)
            if (url.startsWith('/api/')) {
                if (!apiHost) {
                    return Promise.resolve(new Error('Request Failed!'))
                } else {
                    let [opts, ...otherArgs] = args
                    opts = {
                        ...opts,
                        headers: {
                            ...opts.headers,
                            Authorization: `Bearer ${apiKey}`,
                        },
                    }
                    return oldFetch(`${apiHost}${url}`, opts || {}, ...otherArgs)
                }
            }
            return oldFetch(url, ...args)
        }
        return () => {
            window.fetch = oldFetch
        }
    }, [connection])

    return <Story {...context} />
}
