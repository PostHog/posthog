import { actions, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { lemonTextMarkdownLogicType } from './lemonTextMarkdown.logicType'
import api from 'lib/api'
import { MediaUploadResponse } from '~/types'

export const lemonTextMarkdownLogic = kea<lemonTextMarkdownLogicType>([
    path(['lib', 'components', 'LemonTextArea', 'lemonTextMarkdownLogic']),
    actions({}),
    loaders({
        media: [
            null as MediaUploadResponse | null,
            {
                uploadImage: async (file: File) => {
                    const formData = new FormData()
                    formData.append('image', file)
                    return await api.media.upload(formData)
                },
            },
        ],
    }),
    selectors({
        markdownURL: [
            (s) => [s.media],
            (media) => {
                if (media) {
                    return `![${media.name}](${media.image_location})`
                }
                return ''
            },
        ],
    }),
])
