import { encodeParams } from 'kea-router'

export function appEditorUrl(actionId, appUrl) {
    const params = {
        userIntent: 'add-action',
        ...(actionId ? { actionId } : {}),
        ...(appUrl ? { appUrl } : {}),
    }
    return '/api/user/redirect_to_site/' + encodeParams(params, '?')
}

export const defaultUrl = 'https://'
