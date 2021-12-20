import { encodeParams } from 'kea-router'
import { EditorProps } from '~/types'

/** defaultIntent: whether to launch with empty intent (i.e. toolbar mode is default) */
export function appEditorUrl(appUrl?: string, actionId?: number, defaultIntent?: boolean): string {
    const params: EditorProps = {
        userIntent: defaultIntent ? undefined : actionId ? 'edit-action' : 'add-action',
        ...(actionId ? { actionId } : {}),
        ...(appUrl ? { appUrl } : {}),
    }
    return '/api/user/redirect_to_site/' + encodeParams(params, '?')
}

export const defaultUrl = 'https://'
