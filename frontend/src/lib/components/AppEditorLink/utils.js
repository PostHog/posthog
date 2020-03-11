export function appEditorUrl(actionId, appUrl) {
    return (
        '/api/user/redirect_to_site/' +
        (actionId ? '?actionId=' + actionId : '') +
        (appUrl
            ? `${actionId ? '&' : '?'}appUrl=${encodeURIComponent(appUrl)}`
            : '')
    )
}
export const defaultUrl = 'https://'
