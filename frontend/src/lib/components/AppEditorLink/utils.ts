import { encodeParams } from 'kea-router'
import { EditorProps } from '~/types'

export function appEditorUrl(actionId: number, appUrl: string): string {
    const params: EditorProps = {
        userIntent: actionId ? 'edit-action' : 'add-action',
        ...(actionId ? { actionId } : {}),
        ...(appUrl ? { appUrl } : {}),
    }
    return '/api/users/@me/redirect_to_site/' + encodeParams(params, '?')
}

export const defaultUrl = 'https://'
