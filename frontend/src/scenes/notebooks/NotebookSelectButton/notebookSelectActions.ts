import { BuiltLogic } from 'kea'

import { dayjs } from 'lib/dayjs'

import { type notebooksModelType, openNotebook } from '~/models/notebooksModel'

import type { notebookLogicType } from '../Notebook/notebookLogic'
import { NotebookNodeResource, NotebookTarget } from '../types'

type OnNotebookOpened = (notebookLogic: BuiltLogic<notebookLogicType>) => void

/** Opens a notebook in the popover, and adds the resource unless the notebook already holds it. */
export function openNotebookForResource({
    notebookShortId,
    alreadyContainsResource,
    resource,
    onNotebookOpened,
}: {
    notebookShortId: string
    alreadyContainsResource: boolean
    resource?: NotebookNodeResource | boolean
    onNotebookOpened?: OnNotebookOpened
}): void {
    void openNotebook(notebookShortId, NotebookTarget.Popover, (theNotebookLogic) => {
        if (!alreadyContainsResource && resource) {
            theNotebookLogic.actions.insertAfterLastNode([resource])
        }
        onNotebookOpened?.(theNotebookLogic)
    })
}

/** Creates a notebook that starts with the resource, and opens it in the popover. */
export function createNotebookForResource({
    resource,
    newNotebookTitle,
    createNotebook,
    onNotebookOpened,
}: {
    resource?: NotebookNodeResource | boolean
    newNotebookTitle?: string
    createNotebook: notebooksModelType['actions']['createNotebook']
    onNotebookOpened?: OnNotebookOpened
}): void {
    const notebookResource = resource && typeof resource !== 'boolean' ? resource : null
    createNotebook(
        NotebookTarget.Popover,
        newNotebookTitle ?? `Notes ${dayjs().format('DD/MM')}`,
        notebookResource ? [notebookResource] : undefined,
        onNotebookOpened
    )
}
