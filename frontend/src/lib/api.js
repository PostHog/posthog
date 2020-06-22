function getCookie(name) {
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

class Api {
    get(url) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') == -1 && url[url.length - 1] != '/' ? '/' : '')
        }
        return fetch(url).then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw { status: response.status, ...data }
                })
            }
            return response.json()
        })
    }
    update(url, data) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') == -1 && url[url.length - 1] != '/' ? '/' : '')
        }
        return fetch(url, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(data),
        }).then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    if (Array.isArray(data)) {
                        throw data
                    }
                    throw { status: response.status, ...data }
                })
            }
            return response.json()
        })
    }
    create(url, data) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') == -1 && url[url.length - 1] != '/' ? '/' : '')
        }
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(data),
        }).then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    if (Array.isArray(data)) {
                        throw data
                    }
                    throw { status: response.status, ...data }
                })
            }
            return response.json()
        })
    }
    delete(url) {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') == -1 && url[url.length - 1] != '/' ? '/' : '')
        }
        return fetch(url, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCookie('csrftoken'),
            },
        }).then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw { status: response.status, ...data }
                })
            }
            return response
        })
    }
}
let api = new Api()
export default api
