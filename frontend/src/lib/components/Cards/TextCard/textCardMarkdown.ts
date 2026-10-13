import {
    MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    MARKDOWN_BASE_READONLY_EXTENSIONS,
} from 'lib/components/MarkdownEditor/shared/markdownExtensions'
import { createTiptapMarkdownConverter } from 'lib/utils/markdown'

import {
    IMAGE_TILE_MARKDOWN_EDITABLE_EXTENSION,
    IMAGE_TILE_MARKDOWN_READONLY_EXTENSION,
} from 'products/dashboards/frontend/components/ImageTile/imageTileMarkdown'

import { WordArtExtension } from './WordArt/WordArtExtension'

export const TEXT_CARD_MARKDOWN_EXTENSIONS = [
    ...MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    WordArtExtension,
    IMAGE_TILE_MARKDOWN_EDITABLE_EXTENSION,
]

export const TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS = [
    ...MARKDOWN_BASE_READONLY_EXTENSIONS,
    WordArtExtension,
    IMAGE_TILE_MARKDOWN_READONLY_EXTENSION,
]

export const textCardConverter = createTiptapMarkdownConverter(TEXT_CARD_MARKDOWN_EXTENSIONS)
