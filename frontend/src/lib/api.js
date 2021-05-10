import { fromParamsGivenUrl, toParams } from 'lib/utils'
import { Environments, ENVIRONMENT_LOCAL_STORAGE_KEY } from 'lib/constants'

export function getCookie(name) {
    var cookieValue = null
    if (document.cookie && document.cookie !== '') {
        var cookies = document.cookie.split(';')
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim()
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === name + '=') {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1))
                break
            }
        }
    }
    return cookieValue
}

async function getJSONOrThrow(response) {
    try {
        return await response.json()
    } catch (e) {
        return { statusText: response.statusText }
    }
}

class Api {
    async get(url) {
        // TODO: how to put behind a feature flag
        url = maybeAddEnvironmentProperty(url)

        let response
        try {
            response = await fetch(url)
        } catch (e) {
            throw { status: 0, message: e }
        }

        if (!response.ok) {
            const data = await getJSONOrThrow(response)
            throw { status: response.status, ...data }
        }
        return await getJSONOrThrow(response)
    }
    async update(url, data) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }
        const isFormData = data instanceof FormData
        const response = await fetch(url, {
            method: 'PATCH',
            headers: {
                ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: isFormData ? data : JSON.stringify(data),
        })
        if (!response.ok) {
            const jsonData = await getJSONOrThrow(response)
            if (Array.isArray(jsonData)) {
                throw jsonData
            }
            throw { status: response.status, ...jsonData }
        }
        return await getJSONOrThrow(response)
    }
    async create(url, data = undefined) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }
        const isFormData = data instanceof FormData
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: isFormData ? data : JSON.stringify(data),
        })
        if (!response.ok) {
            const jsonData = await getJSONOrThrow(response)
            if (Array.isArray(jsonData)) {
                throw jsonData
            }
            throw { status: response.status, ...jsonData }
        }
        return await getJSONOrThrow(response)
    }
    async delete(url) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }
        const response = await fetch(url, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCookie('csrftoken'),
            },
        })
        if (!response.ok) {
            const data = await getJSONOrThrow(response)
            throw { status: response.status, ...data }
        }
        return response
    }
}

function isWhitelisted(url) {
    const WHITELIST = ['api']

    for (let i = 0; i < WHITELIST.length; i++) {
        const urlWithSlash = '/' + url
        const startsWith = url.indexOf(WHITELIST[i]) === 0 || urlWithSlash.indexOf(WHITELIST[i]) === 0
        if (startsWith) {
            return true
        }
    }

    return false
}

function maybeAddEnvironmentProperty(url) {
    const localStorageEnvironmentValue = window.localStorage.getItem(ENVIRONMENT_LOCAL_STORAGE_KEY)
    const isWhitelistedUrl = isWhitelisted(url)
    const shouldAddEnvironmentValue = localStorageEnvironmentValue && isWhitelistedUrl

    if (shouldAddEnvironmentValue) {
        let urlObject = url.indexOf('http') === 0 ? new URL(url) : new URL(url, window.location.origin)

        let params = fromParamsGivenUrl(urlObject.search)

        const environmentProperty =
            localStorageEnvironmentValue === Environments.PRODUCTION
                ? { key: '$environment', operator: 'is_not', value: ['test'] }
                : { key: '$environment', operator: 'exact', value: ['test'] }

        if (params.properties) {
            let parsedProperties = JSON.parse(params.properties)
            parsedProperties = Array.isArray(parsedProperties)
                ? [...parsedProperties, environmentProperty]
                : [parsedProperties, environmentProperty]
            params.properties = JSON.stringify(parsedProperties)
        } else {
            params.properties = JSON.stringify([environmentProperty])
        }

        return url.indexOf('http') === 0
            ? urlObject.origin + urlObject.pathname + '?' + toParams(params)
            : urlObject.pathname + '?' + toParams(params)
    } else if (url.indexOf('http') !== 0) {
        return '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
    }
}

let api = new Api()
export default api
