import { lemonToast } from '@posthog/lemon-ui'
import api from 'lib/api'

export async function deleteWithUndo<T extends Record<string, any>>({
    undo = false,
    ...props
}: {
    undo?: boolean
    endpoint: string
    object: T
    idField?: keyof T
    callback?: (undo: boolean, object: T) => void
}): Promise<void> {
    await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
        ...props.object,
        deleted: !undo,
    })
    props.callback?.(undo, props.object)
    lemonToast[undo ? 'success' : 'info'](
        <>
            <b>{props.object.name || <i>{props.object.derived_name || 'Unnamed'}</i>}</b> has been{' '}
            {undo ? 'restored' : 'deleted'}
        </>,
        {
            toastId: `delete-item-${props.object.id}-${undo}`,
            button: undo
                ? undefined
                : {
                      label: 'Undo',
                      action: () => deleteWithUndo({ undo: true, ...props }),
                  },
        }
    )
}
