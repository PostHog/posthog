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
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }

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
            const data = await getJSONOrThrow(response)
            if (Array.isArray(data)) {
                throw data
            }
            throw { status: response.status, ...data }
        }
        return await getJSONOrThrow(response)
    }
    async create(url, data) {
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
            const data = await getJSONOrThrow(response)
            if (Array.isArray(data)) {
                throw data
            }
            throw { status: response.status, ...data }
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
let api = new Api()
export default api
