import type { Editor } from '@tiptap/core'
import posthog from 'posthog-js'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

export function useMarkdownEditorImageUpload(editor: Editor | null): ReturnType<typeof useUploadFiles> {
    return useUploadFiles({
        onUpload: (url, fileName) => {
            editor?.chain().focus().setImage({ src: url, alt: fileName }).run()
            posthog.capture('markdown image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('markdown image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })
}
