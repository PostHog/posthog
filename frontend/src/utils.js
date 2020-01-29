export function uuid() {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  }


export let toParams = (obj) => Object.entries(obj).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')
export let fromParams = () => window.location.search != '' ? window.location.search.slice(1).split('&').reduce((a, b) => { b = b.split('='); a[b[0]] = decodeURIComponent(b[1]); return a; }, {}) : {};

export let colors = ['success', 'secondary', 'warning', 'primary', 'danger', 'info', 'dark', 'light']
export let percentage = (division) => division.toLocaleString(undefined, {style: 'percent', maximumFractionDigits: 2})
export let appEditorUrl = (team) => team.app_url + '#state=' + encodeURIComponent(JSON.stringify({'action': 'mpeditor', token: team.api_token}))