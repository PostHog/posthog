import { lemonToast } from '@posthog/lemon-ui'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { getTextFromFile, selectFiles } from 'lib/utils/file-utils'

export function loadNotebookFromJSON(setLocalContent: (jsonContent: JSONContent) => void): void {
    void selectFiles({
        contentType: 'application/json',
        multiple: false,
    })
        .then(async (files) => {
            if (!files.length) {
                return
            }
            const text = await getTextFromFile(files[0])
            const data = JSON.parse(text)
            if (data.type !== 'doc') {
                throw new Error('Not a notebook')
            }
            // Looks like a notebook
            setLocalContent(data)
        })
        .catch((e) => {
            lemonToast.error(e.message)
        })
}
