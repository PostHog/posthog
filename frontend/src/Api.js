function getCookie(name) {
  var cookieValue = null;
  if (document.cookie && document.cookie !== '') {
      var cookies = document.cookie.split(';');
      for (var i = 0; i < cookies.length; i++) {
          var cookie = cookies[i].trim();
          // Does this cookie string begin with the name we want?
          if (cookie.substring(0, name.length + 1) === (name + '=')) {
              cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
              break;
          }
      }
  }
  return cookieValue;
}

class Api {
  get(url, error) { 
    if(url.indexOf('http') !== 0) {
      url = '/' + url + (url.indexOf('?') == -1 ? '/' : '');
    }
    return fetch(url)
      .then((response) => {
        if(!response.ok) {
          throw Error(response.statusText);
        }
        return response.json();
      })
  }
  update(model, data) {
    return fetch('/' + model + '/', {
      method: 'PATCH',
      headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
      },
      body: JSON.stringify(data)
    })
    .then((response) => {
      if(!response.ok) {
        throw Error(response.statusText);
      }
      return response.json();
    })
  }
  create(model, data) {
    return fetch('/' + model + '/', {
      method: 'POST',
      headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
      },
      body: JSON.stringify(data)
    })
    .then((response) => {
      if(!response.ok) {
        throw Error(response.data);
      }
      return response.json();
    })
  }
  delete(model, error) {
    return fetch('/' + model + '/', {
      method: 'DELETE',
      headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': getCookie('csrftoken')
      },
    })
    .then((response) => {
      if(!response.ok) {
        throw Error(response.statusText);
      }
      return response.json();
    })
  }
}
let api = new Api();
export default api;